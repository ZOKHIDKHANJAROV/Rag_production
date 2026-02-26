from fastapi import FastAPI
from pydantic import BaseModel
import requests
import os
import redis
import hashlib
import json

app = FastAPI(title="LLM Service")

OLLAMA_URL = "http://ollama:11434/api/generate"
DEFAULT_MODEL = os.getenv("LLM_MODEL", "llama3:8b")
REQUEST_TIMEOUT = 120

# Redis для кэша
redis_client = redis.Redis(
    host="redis",
    port=6379,
    decode_responses=True
)


class LLMRequest(BaseModel):
    prompt: str
    model: str | None = None
    temperature: float = 0.0
    max_tokens: int = 1024
    stream: bool = False


@app.get("/health")
def health():
    return {"status": "ok"}


def build_cache_key(prompt: str, model: str):
    raw = f"{model}:{prompt}"
    return "llm:" + hashlib.sha256(raw.encode()).hexdigest()


@app.post("/generate")
def generate(req: LLMRequest):

    model = req.model or DEFAULT_MODEL
    cache_key = build_cache_key(req.prompt, model)

    # 🔥 1️⃣ Проверяем кэш
    cached = redis_client.get(cache_key)
    if cached:
        return {
            "response": cached,
            "cached": True
        }

    # 🔥 2️⃣ Запрос к Ollama
    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": model,
                "prompt": req.prompt,
                "stream": False,
                "options": {
                    "temperature": req.temperature,
                    "num_predict": req.max_tokens
                }
            },
            timeout=REQUEST_TIMEOUT
        )

        response.raise_for_status()

    except Exception as e:
        return {
            "error": str(e)
        }

    answer = response.json().get("response", "")

    # 🔥 3️⃣ Кэшируем ответ (10 минут)
    redis_client.setex(cache_key, 600, answer)

    return {
        "response": answer,
        "cached": False
    }