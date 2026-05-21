from fastapi import FastAPI
from pydantic import BaseModel
import httpx
import redis.asyncio as redis
import hashlib
import asyncio
import os

app = FastAPI(title="LLM Service")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434/api/generate")

PRIMARY_MODEL = os.getenv("LLM_MODEL", "mistral:latest")
FALLBACK_MODEL = os.getenv("FALLBACK_MODEL", "llama3:8b")

REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "300"))
RETRY_COUNT = int(os.getenv("RETRY_COUNT", "3"))
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "30m")


# ---------- Redis (async) ----------
redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST", "redis"),
    port=int(os.getenv("REDIS_PORT", "6379")),
    decode_responses=True
)


# ---------- HTTP Client ----------
client: httpx.AsyncClient | None = None


@app.on_event("startup")
async def startup():
    global client
    client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT)


@app.on_event("shutdown")
async def shutdown():
    await client.aclose()


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
def build_cache_key(prompt: str, model: str):
    raw = f"{model}:{prompt}"
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


# ---------- Main endpoint ----------
@app.post("/generate")
async def generate(req: LLMRequest):

    model = req.model or PRIMARY_MODEL

    cache_key = build_cache_key(req.prompt, model)

    # -------- Cache check --------
    cached = await redis_client.get(cache_key)

    if cached:
        return {
            "response": cached,
            "cached": True,
            "model": model
        }

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

    try:

        response = await generate_with_fallback(payload, model)

    except Exception as e:

        return {"error": str(e)}

    answer = response.json().get("response", "")

    # -------- Save cache --------
    await redis_client.setex(cache_key, 600, answer)

    return {
        "response": answer,
        "cached": False,
        "model": model
    }
