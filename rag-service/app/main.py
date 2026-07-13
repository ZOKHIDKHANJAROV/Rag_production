import httpx
import numpy as np
import logging
import os
import asyncio
import redis.asyncio as redis
import json
import hashlib
import re

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
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
REASON_MODEL = os.getenv("REASON_MODEL", "mistral:latest")
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
RAG_RRF_K = int(os.getenv("RAG_RRF_K", "60"))
RAG_MAX_CHUNKS_PER_DOCUMENT = int(os.getenv("RAG_MAX_CHUNKS_PER_DOCUMENT", "1"))

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
INTERNAL_SERVICE_TOKEN = os.getenv("INTERNAL_SERVICE_TOKEN", "")
SERVICE_AUTH_HEADER = "X-Service-Token"
LLM_UNAVAILABLE_MESSAGE = (
    "LLM service is unavailable or the requested Ollama model is not installed. "
    "Relevant sources were found, but generation cannot be completed yet."
)
CITATION_INSTRUCTION = (
    "For every factual claim, cite the supporting source exactly as [filename]. "
    "Use only source labels present below and never invent citations."
)

# ---------------------------
# Redis session memory
# ---------------------------

redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST", "redis"),
    port=int(os.getenv("REDIS_PORT", "6379")),
    decode_responses=True
)

def build_rag_cache_key(question, scope_keys=None, history=None):
    raw = question.strip().lower()
    scopes = ",".join(sorted(scope_keys or ["global"]))
    history_payload = json.dumps(
        history or [],
        ensure_ascii=False,
        separators=(",", ":")
    )
    cache_input = f"{scopes}:{history_payload}:{raw}"
    return f"rag:{RAG_CACHE_VERSION}:" + hashlib.sha256(cache_input.encode()).hexdigest()

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


def service_headers():
    return {SERVICE_AUTH_HEADER: INTERNAL_SERVICE_TOKEN} if INTERNAL_SERVICE_TOKEN else {}


def llm_health_url():
    return f"{LLM_SERVICE_URL.rsplit('/', 1)[0]}/health"


async def check_dependency_health():
    await redis_client.ping()

    llm_response, vector_response = await asyncio.gather(
        client.get(llm_health_url(), timeout=5.0),
        client.get(f"{VECTOR_SERVICE_URL}/health", timeout=5.0),
    )
    llm_response.raise_for_status()
    vector_response.raise_for_status()

    return {
        "redis": "ok",
        "llm": "ok",
        "vector": "ok",
    }


@app.middleware("http")
async def require_service_token(request: Request, call_next):
    if request.url.path in {"/health", "/metrics"}:
        return await call_next(request)

    if not INTERNAL_SERVICE_TOKEN:
        return JSONResponse(
            status_code=503,
            content={"detail": "Internal service token is not configured"},
        )

    provided_token = request.headers.get(SERVICE_AUTH_HEADER, "")
    if provided_token != INTERNAL_SERVICE_TOKEN:
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid internal service token"},
        )

    return await call_next(request)
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
async def health():
    try:
        dependencies = await check_dependency_health()
    except (httpx.HTTPError, redis.RedisError, RuntimeError) as exc:
        logging.error({"event": "healthcheck_failed", "error": str(exc)})
        raise HTTPException(status_code=503, detail="Service unhealthy") from exc

    return {
        "status": "ok",
        "service": "rag-service",
        "dependencies": dependencies,
    }

@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type="text/plain")

# ---------------------------
# Semantic Cache
# ---------------------------

async def check_semantic_cache(question, scope_keys, history):
    cache_key = build_rag_cache_key(question, scope_keys, history)
    cached = await redis_client.get(cache_key)

    if cached:
        try:
            cached_payload = json.loads(cached)
            if not isinstance(cached_payload, dict):
                raise ValueError("cache payload is not an object")
        except (json.JSONDecodeError, ValueError):
            cached_payload = {"answer": cached, "sources": []}

        answer = cached_payload.get("answer", "")
        if is_negative_or_empty_answer(answer):
            logging.info({"event": "rag_cache_negative_ignored"})
            await redis_client.delete(cache_key)
            return None

        logging.info({"event": "rag_cache_hit"})
        return {
            "answer": answer,
            "sources": cached_payload.get("sources", []),
        }

    logging.info({"event": "rag_cache_miss"})
    return None


async def save_semantic_cache(question, answer, sources, scope_keys, history):
    if is_negative_or_empty_answer(answer):
        logging.info({"event": "rag_cache_negative_skipped"})
        return

    await redis_client.setex(
        build_rag_cache_key(question, scope_keys, history),
        RAG_CACHE_TTL,
        json.dumps({"answer": answer, "sources": sources}, ensure_ascii=False)
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


def metadata_score(question, result):
    title = result.get("title") or ""
    section = result.get("section") or ""
    filename = result.get("filename") or ""

    return (
        0.6 * keyword_score(question, title)
        + 0.25 * keyword_score(question, section)
        + 0.15 * keyword_score(question, filename)
    )


def source_label(result):
    label = result.get("filename") or result.get("title") or result.get("document_id") or "source"
    return re.sub(r"[\[\]\r\n]+", " ", str(label)).strip()[:160] or "source"


def build_context_blocks(results):
    return [
        f"[{source_label(result)}]\n{result['text']}"
        for result in results
    ]

# ---------------------------
# Reranker
# ---------------------------

def result_key(result):
    document_id = result.get("document_id") or result.get("id") or ""
    return document_id, result.get("text", "")[:200]


def fuse_search_results(results):
    fused = {}

    for result in results:
        key = result_key(result)
        rank = max(1, int(result.get("query_rank", 1)))
        candidate = fused.get(key)

        if candidate is None:
            candidate = dict(result)
            candidate["rrf_score"] = 0.0
            fused[key] = candidate
        elif result.get("score", 0) > candidate.get("score", 0):
            candidate.update(result)

        candidate["rrf_score"] += 1.0 / (RAG_RRF_K + rank)

    return list(fused.values())


def rank_documents(question, results):
    ranked = fuse_search_results(results)
    query_count = len({result.get("query_index", 0) for result in results})

    for result in ranked:
        result["keyword_score"] = keyword_score(question, result["text"])
        result["metadata_score"] = metadata_score(question, result)
        result["hybrid_score"] = (
            0.65 * result["score"]
            + 0.25 * result["keyword_score"]
            + 0.1 * result["metadata_score"]
        )

    ranked = [
        result for result in ranked
        if result["score"] >= SCORE_THRESHOLD
        or result["hybrid_score"] >= SCORE_THRESHOLD
    ]

    if query_count > 1:
        sort_key = lambda result: (
            result["rrf_score"],
            result["hybrid_score"]
        )
    else:
        sort_key = lambda result: (
            result["hybrid_score"],
            result["rrf_score"]
        )

    return sorted(ranked, key=sort_key, reverse=True)[:RAG_SEARCH_CANDIDATES]


def rerank_documents(question, docs):
    selected = []
    chunks_per_document = {}

    for doc in docs:
        document_id = doc.get("document_id") or doc.get("id") or doc["text"][:200]
        current_count = chunks_per_document.get(document_id, 0)

        if current_count >= RAG_MAX_CHUNKS_PER_DOCUMENT:
            continue

        chunks_per_document[document_id] = current_count + 1
        selected.append(doc)

    return selected

# ---------------------------
# Context trimming
# ---------------------------

def trim_context(contexts):

    total = 0
    trimmed = []
    oversized_fallback = None

    for c in contexts:

        if total + len(c) > MAX_CONTEXT_CHARS:
            if oversized_fallback is None and MAX_CONTEXT_CHARS > 0:
                oversized_fallback = c[:MAX_CONTEXT_CHARS]
            continue

        trimmed.append(c)
        total += len(c)

    return trimmed or ([oversized_fallback] if oversized_fallback else [])

async def parallel_embeddings(answer, contexts):

    async with vector_semaphore:
        answer_task = client.post(
            f"{VECTOR_SERVICE_URL}/embed",
            json={"texts": [answer]},
            headers=service_headers()
        )

        context_task = client.post(
            f"{VECTOR_SERVICE_URL}/embed",
            json={"texts": contexts},
            headers=service_headers()
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
            },
            headers=service_headers()
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
                },
                headers=service_headers()
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

    for query_index, response in enumerate(responses):

        response.raise_for_status()

        for rank, result in enumerate(response.json()["results"], start=1):
            result["query_index"] = query_index
            result["query_rank"] = rank
            results.append(result)

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
        history = await get_history(req.session_id)
        history = history[-MAX_HISTORY_MESSAGES:]
        cache_history = list(history)
        cached_answer = await check_semantic_cache(
            req.question,
            scope_keys,
            cache_history
        )

        if cached_answer:

            return {
                "answer": cached_answer["answer"],
                "sources": cached_answer["sources"],
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

        filtered = rank_documents(req.question, search_results)

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

        contexts = build_context_blocks(reranked)

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

        context_text = f"{CITATION_INSTRUCTION}\n\n" + "\n\n".join(contexts)

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
                    },
                    headers=service_headers()
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
                },
                headers=service_headers()
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

    await save_semantic_cache(req.question, answer, reranked, scope_keys, cache_history)

    return {
        "answer": answer,
        "sources": reranked
    }


@app.post("/ask/stream")
async def ask_stream(req: AskRequest):

    async def event(data):
        return json.dumps(data, ensure_ascii=False) + "\n"

    async def stream():
        RAG_REQUESTS.inc()
        started_at = asyncio.get_running_loop().time()

        logging.info({
            "event": "question_received",
            "stream": True,
            "question": req.question
        })

        scope_keys = sorted(set(req.scope_keys or ["global"]))
        history = await get_history(req.session_id)
        history = history[-MAX_HISTORY_MESSAGES:]
        cache_history = list(history)
        cached_answer = await check_semantic_cache(
            req.question,
            scope_keys,
            cache_history
        )

        if cached_answer:
            yield await event({"type": "delta", "text": cached_answer["answer"], "cached": True})
            yield await event({"type": "done", "sources": cached_answer["sources"], "cached": True})
            RAG_LATENCY.observe(asyncio.get_running_loop().time() - started_at)
            return

        router, queries = await asyncio.gather(
            route_question(req.question),
            generate_search_queries(req.question)
        )

        top_k = max(1, min(int(router.get("top_k", req.top_k)), 10))
        use_compression = bool(router.get("compression", RAG_ENABLE_COMPRESSION))

        history_text = "\n".join(
            [f"{h['role']}: {h['text']}" for h in history]
        )

        vector_started_at = asyncio.get_running_loop().time()
        search_results = await multi_vector_search(
            queries,
            max(top_k, RAG_SEARCH_CANDIDATES),
            scope_keys
        )
        VECTOR_LATENCY.observe(asyncio.get_running_loop().time() - vector_started_at)
        search_results = search_results[:RAG_SEARCH_CANDIDATES * len(queries)]

        filtered = rank_documents(req.question, search_results)

        if not filtered:
            answer = "В базе знаний нет информации по данному вопросу."
            yield await event({"type": "delta", "text": answer})
            yield await event({"type": "done", "sources": []})
            RAG_LATENCY.observe(asyncio.get_running_loop().time() - started_at)
            return

        reranked = await asyncio.to_thread(
            rerank_documents,
            req.question,
            filtered
        )
        reranked = reranked[:RAG_FINAL_TOP_K]

        contexts = build_context_blocks(reranked)

        if use_compression:
            contexts = await compress_documents(contexts, req.question)

        contexts = trim_context(contexts)

        if not contexts:
            answer = "Контекст отсутствует."
            yield await event({"type": "delta", "text": answer})
            yield await event({"type": "done", "sources": []})
            RAG_LATENCY.observe(asyncio.get_running_loop().time() - started_at)
            return

        context_text = f"{CITATION_INSTRUCTION}\n\n" + "\n\n".join(contexts)
        language_instruction = response_language_instruction(req.question)
        prompt = f"""
Ты корпоративный AI ассистент АГМК.
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

        yield await event({"type": "sources", "sources": reranked})

        answer_chunks = []
        llm_started_at = asyncio.get_running_loop().time()

        async with llm_semaphore:
            async with client.stream(
                "POST",
                LLM_SERVICE_URL,
                json={
                    "prompt": prompt,
                    "model": REASON_MODEL,
                    "temperature": 0,
                    "max_tokens": RAG_MAX_ANSWER_TOKENS,
                    "stream": True
                },
                headers=service_headers()
            ) as llm_response:
                llm_response.raise_for_status()

                async for line in llm_response.aiter_lines():
                    if not line:
                        continue

                    data = json.loads(line)

                    if data.get("type") == "error":
                        yield await event({"type": "error", "error": data.get("error", "LLM error")})
                        return

                    token = data.get("text", "")
                    if token:
                        answer_chunks.append(token)
                        yield await event({"type": "delta", "text": token})

        LLM_LATENCY.observe(asyncio.get_running_loop().time() - llm_started_at)

        answer = "".join(answer_chunks)

        if not answer.strip():
            yield await event({
                "type": "delta",
                "text": LLM_UNAVAILABLE_MESSAGE
            })
            yield await event({
                "type": "done",
                "sources": reranked,
                "llm_unavailable": True
            })
            RAG_LATENCY.observe(asyncio.get_running_loop().time() - started_at)
            return

        history.append({"role": "user", "text": req.question})
        history.append({"role": "assistant", "text": answer})
        await save_history(req.session_id, history)
        await save_semantic_cache(req.question, answer, reranked, scope_keys, cache_history)

        yield await event({"type": "done", "sources": reranked})
        RAG_LATENCY.observe(asyncio.get_running_loop().time() - started_at)

    return StreamingResponse(stream(), media_type="application/x-ndjson")
