import httpx
import numpy as np
import logging
import os
import asyncio
import redis.asyncio as redis
import json
import hashlib
import re

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from prometheus_client import Counter, Histogram, generate_latest

app = FastAPI(title="AI Service")

# ---------------------------
# Environment
# ---------------------------

LLM_SERVICE_URL = os.getenv("LLM_SERVICE_URL", "http://llm-service:8002/generate")
VECTOR_SERVICE_URL = os.getenv("VECTOR_SERVICE_URL", "http://embedding-service:8001")

LLM_MODEL = os.getenv("LLM_MODEL", "mistral:latest")
FAST_MODEL = os.getenv("FAST_MODEL", LLM_MODEL)
MID_MODEL = os.getenv("MID_MODEL", LLM_MODEL)
REASON_MODEL = os.getenv("REASON_MODEL", "llama3:8b-instruct-q8_0")
FINAL_MODEL = os.getenv("FINAL_MODEL", LLM_MODEL)

SCORE_THRESHOLD = float(os.getenv("RAG_SCORE_THRESHOLD", "0.25"))
SEMANTIC_THRESHOLD = float(os.getenv("RAG_SEMANTIC_THRESHOLD", "0.30"))
MAX_CONTEXT_CHARS = int(os.getenv("RAG_MAX_CONTEXT_CHARS", "5500"))
MAX_HISTORY_MESSAGES = int(os.getenv("RAG_MAX_HISTORY_MESSAGES", "6"))
RAG_ENABLE_COMPRESSION = os.getenv("RAG_ENABLE_COMPRESSION", "false").lower() == "true"
RAG_ENABLE_QUERY_EXPANSION = os.getenv("RAG_ENABLE_QUERY_EXPANSION", "false").lower() == "true"
RAG_ENABLE_GROUNDING_CHECK = os.getenv("RAG_ENABLE_GROUNDING_CHECK", "false").lower() == "true"
RAG_SEARCH_CANDIDATES = int(os.getenv("RAG_SEARCH_CANDIDATES", "24"))
RAG_FINAL_TOP_K = int(os.getenv("RAG_FINAL_TOP_K", "5"))

CACHE_COLLECTION = "semantic_cache"
CACHE_THRESHOLD = 0.92
RAG_CACHE_TTL = int(os.getenv("RAG_CACHE_TTL", "600"))
RAG_CACHE_VERSION = "lang-v2"
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "60"))
RAG_HTTP_MAX_CONNECTIONS = int(os.getenv("RAG_HTTP_MAX_CONNECTIONS", "200"))
RAG_HTTP_MAX_KEEPALIVE = int(os.getenv("RAG_HTTP_MAX_KEEPALIVE", "50"))
RAG_LLM_CONCURRENCY = int(os.getenv("RAG_LLM_CONCURRENCY", "8"))
RAG_VECTOR_CONCURRENCY = int(os.getenv("RAG_VECTOR_CONCURRENCY", "32"))
RAG_MAX_ANSWER_TOKENS = int(os.getenv("RAG_MAX_ANSWER_TOKENS", "512"))
LLM_UNAVAILABLE_MESSAGE = (
    "LLM service is unavailable or the requested Ollama model is not installed. "
    "Relevant sources were found, but generation cannot be completed yet."
)

# ---------------------------
# Redis session memory
# ---------------------------

redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST", "redis"),
    port=int(os.getenv("REDIS_PORT", "6379")),
    decode_responses=True
)

def build_rag_cache_key(question, scope_keys=None):
    raw = question.strip().lower()
    scopes = ",".join(sorted(scope_keys or ["global"]))
    return f"rag:{RAG_CACHE_VERSION}:" + hashlib.sha256(f"{scopes}:{raw}".encode()).hexdigest()

def is_negative_or_empty_answer(answer):
    normalized = re.sub(r"\s+", " ", (answer or "").strip().lower())

    if not normalized:
        return True

    negative_patterns = (
        "no information",
        "not found",
        "nothing found",
        "no relevant",
        "\u043d\u0435\u0442 \u0438\u043d\u0444\u043e\u0440\u043c\u0430\u0446\u0438\u0438",
        "\u043d\u0435\u0442 \u0442\u0430\u043a\u043e\u0439 \u0438\u043d\u0444\u043e\u0440\u043c\u0430\u0446\u0438\u0438",
        "\u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d",
        "\u043d\u0438\u0447\u0435\u0433\u043e \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d",
        "\u043a\u043e\u043d\u0442\u0435\u043a\u0441\u0442 \u043e\u0442\u0441\u0443\u0442\u0441\u0442\u0432\u0443\u0435\u0442",
    )

    return any(pattern in normalized for pattern in negative_patterns)

def response_language_instruction(question):
    cyrillic_count = sum(1 for ch in question.lower() if "\u0430" <= ch <= "\u044f" or ch == "\u0451")

    if cyrillic_count >= 2:
        return "Answer strictly in Russian. Do not switch to English."

    return "Answer strictly in the same language as the user's question."

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

# ---------------------------
# Async HTTP client
# ---------------------------

client = httpx.AsyncClient(
    timeout=httpx.Timeout(REQUEST_TIMEOUT, connect=5.0),
    limits=httpx.Limits(
        max_connections=RAG_HTTP_MAX_CONNECTIONS,
        max_keepalive_connections=RAG_HTTP_MAX_KEEPALIVE
    )
)
llm_semaphore = asyncio.Semaphore(RAG_LLM_CONCURRENCY)
vector_semaphore = asyncio.Semaphore(RAG_VECTOR_CONCURRENCY)

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
    scope_keys: list[str] = Field(default_factory=lambda: ["global"])

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type="text/plain")

# ---------------------------
# Semantic Cache
# ---------------------------

async def check_semantic_cache(question, scope_keys):
    cache_key = build_rag_cache_key(question, scope_keys)
    cached = await redis_client.get(cache_key)

    if cached:
        if is_negative_or_empty_answer(cached):
            logging.info({"event": "rag_cache_negative_ignored"})
            await redis_client.delete(cache_key)
            return None

        logging.info({"event": "rag_cache_hit"})
        return cached

    logging.info({"event": "rag_cache_miss"})
    return None


async def save_semantic_cache(question, answer, scope_keys):
    if is_negative_or_empty_answer(answer):
        logging.info({"event": "rag_cache_negative_skipped"})
        return

    await redis_client.setex(
        build_rag_cache_key(question, scope_keys),
        RAG_CACHE_TTL,
        answer
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

    words = {
        word
        for word in re.findall(r"[\w\u0400-\u04ff]{3,}", query.lower())
        if len(word) >= 3
    }

    if not words:
        return 0

    text_words = set(re.findall(r"[\w\u0400-\u04ff]{3,}", text.lower()))
    if not text_words:
        return 0

    return len(words & text_words) / len(words)

# ---------------------------
# Reranker
# ---------------------------

def rerank_documents(question, docs):
    docs.sort(
        key=lambda x: x.get("hybrid_score", x.get("score", 0)),
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

    async with vector_semaphore:
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
    language_instruction = response_language_instruction(question)

    prompt = f"""
Оставь только информацию из документов,
которая может помочь ответить на вопрос.
{language_instruction}

Вопрос:
{question}

Документы:
{joined_docs}

Верни сокращённую версию текста.
"""

    async with llm_semaphore:
        resp = await client.post(
            LLM_SERVICE_URL,
            json={
                "prompt": prompt,
                "model": FAST_MODEL,
                "temperature": 0,
                "max_tokens": 512
            }
        )

    data = resp.json()
    text = data.get("response")

    if not text:
        logging.warning({
            "event": "compression_skipped",
            "error": data.get("error", "empty_response")
        })
        return docs

    return [text]


# ---------------------------
# Router (Adaptive RAG)
# ---------------------------

async def route_question(question):
    word_count = len(re.findall(r"[\w\u0400-\u04ff]+", question))
    top_k = 6 if word_count <= 8 else 10
    return {
        "top_k": top_k,
        "compression": RAG_ENABLE_COMPRESSION
    }

# ---------------------------
# Multi query generation
# ---------------------------

async def generate_search_queries(question):
    query = re.sub(r"\s+", " ", question).strip()
    queries = [query]

    if RAG_ENABLE_QUERY_EXPANSION:
        keywords = re.findall(r"[\w\u0400-\u04ff]{4,}", query.lower())
        keyword_query = " ".join(dict.fromkeys(keywords[:12]))
        if keyword_query and keyword_query != query.lower():
            queries.append(keyword_query)

    return queries[:2]

# ---------------------------
# Multi vector search
# ---------------------------

async def multi_vector_search(queries, top_k, scope_keys):

    tasks = []

    for q in queries:

        tasks.append(
            client.post(
                f"{VECTOR_SERVICE_URL}/search",
                json={
                    "query": q,
                    "top_k": top_k,
                    "scope_keys": scope_keys
                }
            )
        )

    try:
        async with vector_semaphore:
            responses = await asyncio.gather(*tasks)
    except httpx.HTTPError as exc:
        logging.warning({"event": "vector_search_unavailable", "error": str(exc)})
        raise HTTPException(
            status_code=503,
            detail="Vector service is not ready"
        ) from exc

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

        # ---------------------------
        # Semantic Cache
        # ---------------------------

        scope_keys = sorted(set(req.scope_keys or ["global"]))
        cached_answer = await check_semantic_cache(req.question, scope_keys)

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

        top_k = max(1, min(int(router.get("top_k", req.top_k)), 10))
        use_compression = bool(router.get("compression", RAG_ENABLE_COMPRESSION))

        logging.info({
            "event": "router_decision",
            "top_k": top_k,
            "compression": use_compression
        })
        
        # ---------------------------
        # Session memory
        # ---------------------------

        history = await get_history(req.session_id)

        history = history[-MAX_HISTORY_MESSAGES:]

        history_text = "\n".join(
            [f"{h['role']}: {h['text']}" for h in history]
        )

        # ---------------------------
        # Vector search
        # ---------------------------

        with VECTOR_LATENCY.time():

            search_results = await multi_vector_search(
                queries,
                max(top_k, RAG_SEARCH_CANDIDATES),
                scope_keys
            )
            search_results = search_results[:RAG_SEARCH_CANDIDATES * len(queries)]

        # ---------------------------
        # Deduplicate
        # ---------------------------

        seen = set()
        unique = []

        for r in search_results:

            doc_id = r.get("document_id") or r.get("id") or ""
            chunk_key = (doc_id, r["text"][:200])

            if chunk_key not in seen:

                seen.add(chunk_key)
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
            if r["score"] >= SCORE_THRESHOLD or r["hybrid_score"] >= SCORE_THRESHOLD
        ]

        filtered = filtered[:RAG_SEARCH_CANDIDATES]

        if not filtered:

            return {
                "answer": "В базе знаний нет информации по данному вопросу.",
                "sources": []
            }

        # ---------------------------
        # Reranker
        # ---------------------------

        reranked = await asyncio.to_thread(
            rerank_documents,
            req.question,
            filtered
        )
        reranked = reranked[:RAG_FINAL_TOP_K]

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
                "answer": "Контекст отсутствует.",
                "sources": []
            }

        context_text = "\n\n".join(contexts)

        # ---------------------------
        # Prompt
        # ---------------------------

        language_instruction = response_language_instruction(req.question)
        prompt = f"""
Ты корпоративный AI ассистент.
{language_instruction}
Используй только контекст ниже и историю диалога, если она помогает понять вопрос.
Если в контексте нет ответа, прямо скажи, что в базе знаний нет такой информации.
Не выдумывай факты, номера, даты и имена.
Отвечай кратко, но полно.

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

            async with llm_semaphore:
                llm_response = await client.post(
                    LLM_SERVICE_URL,
                    json={
                        "prompt": prompt,
                        "model": REASON_MODEL,
                        "temperature": 0,
                        "max_tokens": RAG_MAX_ANSWER_TOKENS
                    }
                )

        llm_response.raise_for_status()

    answer_data = llm_response.json()
    answer = answer_data.get("response", "")

    if answer_data.get("error"):
        logging.warning({"event": "final_llm_error", "error": answer_data.get("error")})

    # ---------------------------
    # Fallback model
    # ---------------------------

    if len(answer.strip()) < 5:

        logging.info({"event": "fallback_model_triggered"})

        async with llm_semaphore:
            fallback_resp = await client.post(
                LLM_SERVICE_URL,
                json={
                    "prompt": prompt,
                    "model": FINAL_MODEL,
                    "temperature": 0,
                    "max_tokens": RAG_MAX_ANSWER_TOKENS
                }
            )

        fallback_data = fallback_resp.json()
        answer = fallback_data.get("response", "")

        if fallback_data.get("error"):
            logging.warning({"event": "fallback_llm_error", "error": fallback_data.get("error")})

    if not answer.strip():
        logging.warning({"event": "llm_answer_unavailable"})
        return {
            "answer": LLM_UNAVAILABLE_MESSAGE,
            "sources": reranked,
            "llm_unavailable": True
        }


    if RAG_ENABLE_GROUNDING_CHECK:
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
                "answer": "Ответ не подтверждён базой знаний.",
                "sources": []
            }
    # ---------------------------
    # Save session
    # ---------------------------

    history.append({"role": "user", "text": req.question})
    history.append({"role": "assistant", "text": answer})

    await save_history(req.session_id, history)

    # ---------------------------
    # Save semantic cache
    # ---------------------------

    await save_semantic_cache(req.question, answer, scope_keys)

    return {
        "answer": answer,
        "sources": reranked
    }
