import httpx
from fastapi import FastAPI
from pydantic import BaseModel
import numpy as np
import requests
import os

app = FastAPI(title="RAG Service")

LLM_SERVICE_URL = os.getenv("LLM_SERVICE_URL", "http://llm-service:8002/generate")
VECTOR_SERVICE_URL = os.getenv("VECTOR_SERVICE_URL", "http://embedding-service:8001")

LLM_MODEL = os.getenv("LLM_MODEL", "llama3:8b")

SCORE_THRESHOLD = 0.30
SEMANTIC_THRESHOLD = 0.30


class AskRequest(BaseModel):
    question: str
    top_k: int = 5


def cosine_similarity(a, b):
    a = np.array(a)
    b = np.array(b)
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))


@app.post("/ask")
def ask(req: AskRequest):

    # 🔎 1️⃣ Поиск в vector DB
    search_resp = requests.post(
        f"{VECTOR_SERVICE_URL}/search",
        json={"query": req.question, "top_k": req.top_k}
    )
    search_resp.raise_for_status()

    search_results = search_resp.json()["results"]

    # 🎯 2️⃣ Фильтр по score
    filtered = [r for r in search_results if r["score"] >= SCORE_THRESHOLD]

    if not filtered:
        return {
            "answer": "В базе знаний нет информации по данному вопросу.",
            "sources": []
        }

    contexts = [r["text"] for r in filtered]
    context_text = "\n\n".join(contexts)

    # 🧠 3️⃣ Строгий prompt
    prompt = f"""
Ты корпоративный AI-ассистент.

Тебе ЗАПРЕЩЕНО:
- использовать внешние знания
- дополнять информацию
- интерпретировать вне контекста

Ты должен:
- отвечать строго на основе предоставленного контекста
- если информации недостаточно — написать:
  "В базе знаний нет информации по данному вопросу."

Контекст:
{context_text}

Вопрос:
{req.question}

Ответ:
"""

    # 🚀 4️⃣ Запрос к LLM-service (НЕ к Ollama!)
    llm_response = requests.post(
        LLM_SERVICE_URL,
        json={
            "prompt": prompt,
            "model": LLM_MODEL,
            "temperature": 0.0,
            "max_tokens": 1024
        }
    )

    llm_response.raise_for_status()

    answer = llm_response.json().get("response", "")

    # 🧠 5️⃣ Semantic grounding check

    # embedding ответа
    answer_embed_resp = requests.post(
        f"{VECTOR_SERVICE_URL}/embed",
        json={"texts": [answer]}
    )
    answer_vector = answer_embed_resp.json()["embeddings"][0]

    # embedding контекста
    context_embed_resp = requests.post(
        f"{VECTOR_SERVICE_URL}/embed",
        json={"texts": contexts}
    )
    context_vectors = context_embed_resp.json()["embeddings"]

    max_similarity = max(
        cosine_similarity(answer_vector, ctx_vec)
        for ctx_vec in context_vectors
    )

    if max_similarity < SEMANTIC_THRESHOLD:
        return {
            "answer": "Ответ не подтверждён базой знаний.",
            "sources": []
        }

    return {
        "answer": answer,
        "sources": filtered
    }