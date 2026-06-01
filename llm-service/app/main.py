from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import httpx
import redis.asyncio as redis
import hashlib
import asyncio
import os
import json

app = FastAPI(title="LLM Service")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434/api/generate")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama").lower()
VLLM_BASE_URL = os.getenv("VLLM_BASE_URL", "http://vllm-service:8000/v1").rstrip("/")
VLLM_MODEL = os.getenv("VLLM_MODEL", "rag-model")

PRIMARY_MODEL = os.getenv("LLM_MODEL", "mistral:latest")
FALLBACK_MODEL = os.getenv("FALLBACK_MODEL", "llama3:8b")

REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "60"))
RETRY_COUNT = int(os.getenv("RETRY_COUNT", "3"))
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "30m")
LLM_CONCURRENCY = int(os.getenv("LLM_CONCURRENCY", "4"))
LLM_HTTP_MAX_CONNECTIONS = int(os.getenv("LLM_HTTP_MAX_CONNECTIONS", "50"))
LLM_HTTP_MAX_KEEPALIVE = int(os.getenv("LLM_HTTP_MAX_KEEPALIVE", "20"))


# ---------- Redis (async) ----------
redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST", "redis"),
    port=int(os.getenv("REDIS_PORT", "6379")),
    decode_responses=True
)


# ---------- HTTP Client ----------
client: httpx.AsyncClient | None = None
llm_semaphore = asyncio.Semaphore(LLM_CONCURRENCY)
cache_locks: dict[str, asyncio.Lock] = {}


@app.on_event("startup")
async def startup():
    global client
    client = httpx.AsyncClient(
        timeout=httpx.Timeout(REQUEST_TIMEOUT, connect=5.0),
        limits=httpx.Limits(
            max_connections=LLM_HTTP_MAX_CONNECTIONS,
            max_keepalive_connections=LLM_HTTP_MAX_KEEPALIVE
        )
    )


@app.on_event("shutdown")
async def shutdown():
    await client.aclose()
    await redis_client.aclose()


# ---------- Request schema ----------
class LLMRequest(BaseModel):
    prompt: str
    model: str | None = None
    temperature: float = 0.0
    max_tokens: int = 1024
    stream: bool = False


# ---------- Health ----------
@app.get("/health")
def health():
    return {"status": "ok"}


# ---------- Cache key ----------
def build_cache_key(prompt: str, model: str, temperature: float, max_tokens: int):
    raw = f"{model}:{temperature}:{max_tokens}:{prompt}"
    return "llm:" + hashlib.sha256(raw.encode()).hexdigest()


# ---------- Retry ----------
async def retry_request(payload):

    for attempt in range(RETRY_COUNT):

        try:

            response = await client.post(
                OLLAMA_URL,
                json=payload
            )

            response.raise_for_status()

            return response

        except Exception as e:

            if attempt == RETRY_COUNT - 1:
                raise e

            await asyncio.sleep(1)


# ---------- Fallback ----------
async def generate_with_fallback(payload, model):

    try:
        payload["model"] = model
        return await retry_request(payload)

    except Exception:

        payload["model"] = FALLBACK_MODEL
        return await retry_request(payload)


def provider_model(request_model: str):
    if LLM_PROVIDER == "vllm":
        return VLLM_MODEL

    return request_model


async def vllm_completion(payload):
    response = await client.post(
        f"{VLLM_BASE_URL}/chat/completions",
        headers={"Authorization": "Bearer not-needed"},
        json=payload
    )
    response.raise_for_status()
    return response


async def stream_vllm_with_cache(payload, cache_key, model):
    chunks = []

    try:
        async with llm_semaphore:
            async with client.stream(
                "POST",
                f"{VLLM_BASE_URL}/chat/completions",
                headers={"Authorization": "Bearer not-needed"},
                json=payload
            ) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue

                    raw = line.removeprefix("data: ").strip()
                    if raw == "[DONE]":
                        answer = "".join(chunks)
                        if answer:
                            await redis_client.setex(cache_key, 600, answer)

                        yield json.dumps({"type": "done", "model": model}, ensure_ascii=False) + "\n"
                        return

                    data = json.loads(raw)
                    choice = data.get("choices", [{}])[0]
                    token = choice.get("delta", {}).get("content", "")

                    if token:
                        chunks.append(token)
                        yield json.dumps(
                            {"type": "delta", "text": token, "model": model},
                            ensure_ascii=False
                        ) + "\n"

    except Exception as e:
        yield json.dumps({"type": "error", "error": str(e)}, ensure_ascii=False) + "\n"


async def stream_with_cache(payload, cache_key, model):
    chunks = []

    try:
        async with llm_semaphore:
            async with client.stream("POST", OLLAMA_URL, json=payload) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    if not line:
                        continue

                    data = json.loads(line)
                    token = data.get("response", "")

                    if token:
                        chunks.append(token)
                        yield json.dumps(
                            {"type": "delta", "text": token, "model": data.get("model", model)},
                            ensure_ascii=False
                        ) + "\n"

                    if data.get("done"):
                        answer = "".join(chunks)
                        if answer:
                            await redis_client.setex(cache_key, 600, answer)

                        yield json.dumps(
                            {"type": "done", "model": data.get("model", model)},
                            ensure_ascii=False
                        ) + "\n"
                        return

    except Exception as e:
        yield json.dumps({"type": "error", "error": str(e)}, ensure_ascii=False) + "\n"


# ---------- Main endpoint ----------
@app.post("/generate")
async def generate(req: LLMRequest):

    requested_model = req.model or PRIMARY_MODEL
    model = provider_model(requested_model)

    cache_key = build_cache_key(req.prompt, model, req.temperature, req.max_tokens)

    # -------- Cache check --------
    cached = await redis_client.get(cache_key)

    if cached:
        if req.stream:
            async def cached_stream():
                yield json.dumps(
                    {"type": "delta", "text": cached, "cached": True, "model": model},
                    ensure_ascii=False
                ) + "\n"
                yield json.dumps(
                    {"type": "done", "cached": True, "model": model},
                    ensure_ascii=False
                ) + "\n"

            return StreamingResponse(cached_stream(), media_type="application/x-ndjson")

        return {
            "response": cached,
            "cached": True,
            "model": model
        }

    lock = cache_locks.setdefault(cache_key, asyncio.Lock())
    async with lock:
        cached = await redis_client.get(cache_key)
        if cached:
            if req.stream:
                async def locked_cached_stream():
                    yield json.dumps(
                        {"type": "delta", "text": cached, "cached": True, "model": model},
                        ensure_ascii=False
                    ) + "\n"
                    yield json.dumps(
                        {"type": "done", "cached": True, "model": model},
                        ensure_ascii=False
                    ) + "\n"

                return StreamingResponse(locked_cached_stream(), media_type="application/x-ndjson")

            return {
                "response": cached,
                "cached": True,
                "model": model
            }

        if LLM_PROVIDER == "vllm":
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": req.prompt}],
                "stream": req.stream,
                "temperature": req.temperature,
                "max_tokens": req.max_tokens
            }
        else:
            payload = {
                "prompt": req.prompt,
                "model": model,
                "stream": req.stream,
                "temperature": req.temperature,
                "max_tokens": req.max_tokens
            }

        if req.stream:
            if LLM_PROVIDER == "vllm":
                return StreamingResponse(
                    stream_vllm_with_cache(payload, cache_key, model),
                    media_type="application/x-ndjson"
                )

            payload = {
                "prompt": req.prompt,
                "model": model,
                "stream": True,
                "keep_alive": OLLAMA_KEEP_ALIVE,
                "options": {
                    "temperature": req.temperature,
                    "num_predict": req.max_tokens
                }
            }
            return StreamingResponse(
                stream_with_cache(payload, cache_key, model),
                media_type="application/x-ndjson"
            )

        try:
            async with llm_semaphore:
                if LLM_PROVIDER == "vllm":
                    response = await vllm_completion(payload)
                else:
                    payload = {
                        "prompt": req.prompt,
                        "model": model,
                        "stream": False,
                        "keep_alive": OLLAMA_KEEP_ALIVE,
                        "options": {
                            "temperature": req.temperature,
                            "num_predict": req.max_tokens
                        }
                    }
                    response = await generate_with_fallback(payload, model)
        except Exception as e:
            return {"error": str(e)}

        if LLM_PROVIDER == "vllm":
            answer = response.json().get("choices", [{}])[0].get("message", {}).get("content", "")
        else:
            answer = response.json().get("response", "")

        # -------- Save cache --------
        await redis_client.setex(cache_key, 600, answer)

    return {
        "response": answer,
        "cached": False,
        "model": model
    }
