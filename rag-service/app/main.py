import httpx
import numpy as np
import logging
import os
import asyncio
import redis.asyncio as redis
import json
import re

from sentence_transformers import CrossEncoder
from fastapi import FastAPI
from fastapi.responses import Response
from pydantic import BaseModel
from prometheus_client import Counter, Histogram, generate_latest

app = FastAPI(title="AI Service")

# ---------------------------
# Models
# ---------------------------

reranker = CrossEncoder("BAAI/bge-reranker-base")

# ---------------------------
# Environment
# ---------------------------

LLM_SERVICE_URL = os.getenv("LLM_SERVICE_URL", "http://llm-service:8002/generate")
VECTOR_SERVICE_URL = os.getenv("VECTOR_SERVICE_URL", "http://embedding-service:8001")

#LLM_MODEL = os.getenv("LLM_MODEL", "llama3:8b-instruct-q8_0")
FAST_MODEL = os.getenv("FAST_MODEL", "qwen3.5:0.8b")
MID_MODEL = os.getenv("MID_MODEL", "qwen3.5:4b")
REASON_MODEL = os.getenv("REASON_MODEL", "qwen3.5:9b")
FINAL_MODEL = os.getenv("FINAL_MODEL", "llama3:8b-instruct-q8_0")

SCORE_THRESHOLD = 0.30
SEMANTIC_THRESHOLD = 0.30
MAX_CONTEXT_CHARS = 6000

CACHE_COLLECTION = "semantic_cache"
CACHE_THRESHOLD = 0.92

LANG_MESSAGES = {
    "ru": {
        "no_info": "В базе знаний нет информации по данному вопросу.",
        "no_context": "Контекст отсутствует.",
        "not_grounded": "Ответ не подтверждён базой знаний."
    },
    "en": {
        "no_info": "There is no information in the knowledge base for this question.",
        "no_context": "Context is empty.",
        "not_grounded": "The answer is not grounded in the knowledge base."
    }
}

# ---------------------------
# Redis session memory
# ---------------------------

redis_client = redis.Redis(
    host="redis",
    port=6379,
    decode_responses=True
)

def _normalize_query_words(query: str):
    return {word for word in query.lower().split() if word}


async def get_history(session_id):

    history = await redis_client.get(session_id)

    if not history:
        return []

    return json.loads(history)


async def save_history(session_id, history):

    await redis_client.set(
        session_id,
        json.dumps(history),
        ex=3600
    )


def detect_question_language(question: str) -> str:
    if re.search(r"[а-яА-ЯёЁ]", question):
        return "ru"
    return "en"


def language_instruction(lang: str) -> str:
    if lang == "ru":
        return "Отвечай строго на том же языке, на котором задан вопрос."
    return "Answer strictly in the same language as the question."


def localized_text(lang: str, key: str) -> str:
    return LANG_MESSAGES.get(lang, LANG_MESSAGES["en"])[key]

# ---------------------------
# Async HTTP client
# ---------------------------

client = httpx.AsyncClient(timeout=60)

@app.on_event("shutdown")
async def shutdown_event():
    await client.aclose()
    await redis_client.aclose()

# ---------------------------
# Logging
# ---------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

# ---------------------------
# Metrics
# ---------------------------

RAG_REQUESTS = Counter(
    "rag_requests_total",
    "Total number of RAG requests"
)

RAG_LATENCY = Histogram(
    "rag_pipeline_latency_seconds",
    "Latency of the RAG pipeline"
)

VECTOR_LATENCY = Histogram(
    "vector_search_latency_seconds",
    "Latency of vector search"
)

LLM_LATENCY = Histogram(
    "llm_latency_seconds",
    "Latency of LLM generation"
)

# ---------------------------
# Request schema
# ---------------------------

class AskRequest(BaseModel):
    question: str
    session_id: str
    top_k: int = 10

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type="text/plain")

# ---------------------------
# Semantic Cache
# ---------------------------

async def check_semantic_cache(question):

    resp = await client.post(
        f"{VECTOR_SERVICE_URL}/search",
        json={
            "query": question,
            "top_k": 1,
            "collection": CACHE_COLLECTION
        }
    )

    results = resp.json().get("results", [])

    if not results:

        logging.info({"event": "semantic_cache_miss"})
        return None

    best = results[0]

    if best["score"] > CACHE_THRESHOLD:

        logging.info({
            "event": "semantic_cache_hit",
            "score": best["score"]
        })

        payload = best.get("payload", {})
        return payload.get("text")

    logging.info({"event": "semantic_cache_miss"})

    return None


async def save_semantic_cache(question, answer):

    await client.post(
        f"{VECTOR_SERVICE_URL}/index",
        json={
            "texts": [question],
            "payload": {"text": answer},
            "collection": CACHE_COLLECTION
        }
    )

# ---------------------------
# Similarity
# ---------------------------

def cosine_similarity(a, b):

    a = np.array(a)
    b = np.array(b)

    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

# ---------------------------
# Keyword scoring
# ---------------------------

def keyword_score(query, text):

    words = _normalize_query_words(query)
    lowered_text = text.lower()

    score = 0

    for w in words:

        if w in lowered_text:
            score += 1

    return score

# ---------------------------
# Reranker
# ---------------------------

def rerank_documents(question, docs):

    pairs = [(question, d["text"]) for d in docs]

    scores = reranker.predict(pairs)

    for i, score in enumerate(scores):

        docs[i]["rerank_score"] = float(score)

    docs.sort(
        key=lambda x: x["rerank_score"],
        reverse=True
    )

    return docs

# ---------------------------
# Context trimming
# ---------------------------

def trim_context(contexts):

    total = 0
    trimmed = []

    for c in contexts:

        if total + len(c) > MAX_CONTEXT_CHARS:
            break

        trimmed.append(c)
        total += len(c)

    return trimmed

async def parallel_embeddings(answer, contexts):

    answer_task = client.post(
        f"{VECTOR_SERVICE_URL}/embed",
        json={"texts": [answer]}
    )

    context_task = client.post(
        f"{VECTOR_SERVICE_URL}/embed",
        json={"texts": contexts}
    )

    answer_resp, context_resp = await asyncio.gather(
        answer_task,
        context_task
    )

    answer_vector = answer_resp.json()["embeddings"][0]
    context_vectors = context_resp.json()["embeddings"]

    return answer_vector, context_vectors

# ---------------------------
# Document compression
# ---------------------------

async def compress_documents(docs, question):

    joined_docs = "\n\n".join(docs)

    prompt = f"""
Оставь только информацию из документов,
которая может помочь ответить на вопрос.

Вопрос:
{question}

Документы:
{joined_docs}

Верни сокращённую версию текста.
"""

    resp = await client.post(
        LLM_SERVICE_URL,
        json={
            "prompt": prompt,
            "model": FAST_MODEL,
            "temperature": 0
        }
    )

    text = resp.json()["response"]

    return [text]


# ---------------------------
# Router (Adaptive RAG)
# ---------------------------

async def route_question(question):

    prompt = f"""
Определи параметры поиска документов.

Вопрос:
{question}

Ответь JSON:

{{
"top_k": число от 2 до 10,
"compression": true или false
}}
"""

    resp = await client.post(
        LLM_SERVICE_URL,
        json={
            "prompt": prompt,
            "model": FAST_MODEL,
            "temperature": 0
        }
    )

    text = resp.json().get("response", "")

    try:
        return json.loads(text)
    except:
        return {
            "top_k": 5,
            "compression": True
        }

# ---------------------------
# Multi query generation
# ---------------------------

async def generate_search_queries(question):

    prompt = f"""
Сгенерируй 3 различных поисковых запроса
для поиска информации в корпоративных документах.

Вопрос:
{question}

Верни только список.
"""

    resp = await client.post(
        LLM_SERVICE_URL,
        json={
            "prompt": prompt,
            "model": FAST_MODEL,
            "temperature": 0.2,
            "max_tokens": 200
        }
    )

    text = resp.json().get("response", "")

    queries = [
        q.strip("- ").strip()
        for q in text.split("\n")
        if q.strip()
    ]

    queries.append(question)

    unique_queries = []
    seen = set()
    for query in queries:
        normalized = query.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        unique_queries.append(query)

    return unique_queries[:4]

# ---------------------------
# Multi vector search
# ---------------------------

async def multi_vector_search(queries, top_k):

    tasks = []

    for q in queries:

        tasks.append(
            client.post(
                f"{VECTOR_SERVICE_URL}/search",
                json={
                    "query": q,
                    "top_k": top_k
                }
            )
        )

    responses = await asyncio.gather(*tasks)

    results = []

    for r in responses:

        r.raise_for_status()

        results.extend(r.json()["results"])

    return results

# ---------------------------
# RAG endpoint
# ---------------------------

@app.post("/ask")
async def ask(req: AskRequest):

    RAG_REQUESTS.inc()

    logging.info({
        "event": "question_received",
        "question": req.question
    })

    with RAG_LATENCY.time():
        lang = detect_question_language(req.question)
        lang_rule = language_instruction(lang)

        # ---------------------------
        # Semantic Cache
        # ---------------------------

        cached_answer = await check_semantic_cache(req.question)

        if cached_answer:

            return {
                "answer": cached_answer,
                "sources": [],
                "cached": True
            }

        # ---------------------------
        # Router and Multi query
        # ---------------------------

        router_task = route_question(req.question)
        query_task = generate_search_queries(req.question)

        router, queries = await asyncio.gather(
            router_task,
            query_task
        )        

        logging.info({
            "event": "multi_query_generated",
            "queries": queries
        })

        top_k = router.get("top_k", req.top_k)
        use_compression = router.get("compression", True)

        logging.info({
            "event": "router_decision",
            "top_k": top_k,
            "compression": use_compression
        })
        
        # ---------------------------
        # Session memory
        # ---------------------------

        history = await get_history(req.session_id)

        history = history[-10:]

        history_text = "\n".join(
            [f"{h['role']}: {h['text']}" for h in history]
        )

        # ---------------------------
        # Vector search
        # ---------------------------

        with VECTOR_LATENCY.time():

            search_results = await multi_vector_search(
                queries,
                top_k
            )
            search_results = search_results[:50]

        # ---------------------------
        # Deduplicate
        # ---------------------------

        seen = set()
        unique = []

        for r in search_results:

            doc_id = r.get("document_id") or r.get("id") or r["text"][:50]

            if doc_id not in seen:

                seen.add(doc_id)
                unique.append(r)

        search_results = unique

        # ---------------------------
        # Hybrid retrieval
        # ---------------------------

        for r in search_results:

            r["keyword_score"] = keyword_score(
                req.question,
                r["text"]
            )

            r["hybrid_score"] = (
                0.7 * r["score"] +
                0.3 * r["keyword_score"]
            )

        search_results.sort(
            key=lambda x: x["hybrid_score"],
            reverse=True
        )

        filtered = [
            r for r in search_results
            if r["score"] >= SCORE_THRESHOLD
        ]

        filtered = filtered[:20]

        if not filtered:

            return {
                "answer": "В базе знаний нет информации по данному вопросу.",
                "sources": []
            }

        # ---------------------------
        # Early Answer task
        # ---------------------------           
        early_contexts = [
            r["text"] for r in filtered[:3]
        ]
        early_context_text = "\n\n".join(early_contexts)
        early_prompt = f"""
        Ты корпоративный AI ассистент.

        Ты должен:
        - отвечать строго на основе предоставленного контекста
        - если информации недостаточно — написать:
        "В базе знаний нет информации по данному вопросу!!."
        Контекст:
        {early_context_text}

        Вопрос:
        {req.question}

        Ответ:
        """

        early_llm_task = client.post(
            LLM_SERVICE_URL,
            json={
                "prompt": early_prompt,
                "model": FAST_MODEL,
                "temperature": 0,
                "max_tokens": 300
            }
        )

        # ---------------------------
        # Reranker
        # ---------------------------

        rerank_task = asyncio.to_thread(
            rerank_documents,
            req.question,
            filtered
        )
        early_resp, reranked = await asyncio.gather(
            early_llm_task,
            rerank_task
        )

        early_resp.raise_for_status()

        early_answer = early_resp.json().get("response", "")

        if len(early_answer.split()) > 10:

            logging.info({
                "event": "early_answer_used"
            })

            return {
                "answer": early_answer,
                "sources": search_results[:3],
                "early": True
            }
        reranked = reranked[:5]

        contexts = [r["text"] for r in reranked]

        # ---------------------------
        # Compression
        # ---------------------------

        if use_compression:

            contexts = await compress_documents(
                contexts,
                req.question
            )

        # ---------------------------
        # Context trim
        # ---------------------------

        contexts = trim_context(contexts)

        if not contexts:

            return {
                "answer": localized_text(lang, "no_context"),
                "sources": []
            }

        context_text = "\n\n".join(contexts)

        # ---------------------------
        # Prompt
        # ---------------------------

        prompt = f"""
Ты корпоративный AI ассистент.

Ты должен:
- отвечать строго на основе предоставленного контекста"
История диалога:
{history_text}

Контекст:
{context_text}

Вопрос:
{req.question}

Ответ:
"""

        # ---------------------------
        # LLM
        # ---------------------------

        with LLM_LATENCY.time():

            llm_response = await client.post(
                LLM_SERVICE_URL,
                json={
                    "prompt": prompt,
                    "model": FINAL_MODEL,
                    "temperature": 0,
                    "max_tokens": 1024
                }
            )

        llm_response.raise_for_status()

    answer = llm_response.json().get("response", "")

    # ---------------------------
    # Fallback model
    # ---------------------------

    if len(answer.strip()) < 5:

        logging.info({"event": "fallback_model_triggered"})

        fallback_resp = await client.post(
            LLM_SERVICE_URL,
            json={
                "prompt": prompt,
                "model": FINAL_MODEL,
                "temperature": 0,
                "max_tokens": 1024
            }
        )

        answer = fallback_resp.json().get("response", "")


    # ---------------------------
    # Parallel Embedding
    # ---------------------------

    answer_vector, context_vectors = await parallel_embeddings(
        answer,
        contexts
    )

    # ---------------------------
    # Grounding check
    # ---------------------------

    max_similarity = max(
        cosine_similarity(answer_vector, ctx_vec)
        for ctx_vec in context_vectors
    )

    logging.info({
        "event": "grounding_check",
        "similarity": float(max_similarity)
    })

    if max_similarity < SEMANTIC_THRESHOLD:

        logging.info({
            "event": "grounding_failed"
        })

        return {
            "answer": localized_text(lang, "not_grounded"),
            "sources": []
        }
    # ---------------------------
    # Save session
    # ---------------------------

    history.append({"role": "user", "text": req.question})
    history.append({"role": "assistant", "text": answer})

    await asyncio.gather(
        save_history(req.session_id, history),
        save_semantic_cache(req.question, answer)
    )

    return {
        "answer": answer,
        "sources": reranked
    }
