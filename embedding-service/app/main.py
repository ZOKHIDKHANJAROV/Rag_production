from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import List, Optional
import uuid
import asyncio
import os
from collections import defaultdict
from qdrant_client.models import (
    Filter,
    FieldCondition,
    IsEmptyCondition,
    MatchAny,
    MatchValue
)

from app.model import embed_texts, get_vector_size
from app.qdrant_client import client, init_collection, collection_exists, COLLECTION_NAME

app = FastAPI(title="Vector Service")
EMBEDDING_CONCURRENCY = int(os.getenv("EMBEDDING_CONCURRENCY", "4"))
INTERNAL_SERVICE_TOKEN = os.getenv("INTERNAL_SERVICE_TOKEN", "")
SERVICE_AUTH_HEADER = "X-Service-Token"
embedding_semaphore = asyncio.Semaphore(EMBEDDING_CONCURRENCY)


@app.middleware("http")
async def require_service_token(request: Request, call_next):
    if request.url.path == "/health":
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


async def embed_texts_async(texts: List[str]):
    async with embedding_semaphore:
        return await asyncio.to_thread(embed_texts, texts)


# =========================
# Request Models
# =========================

class EmbedRequest(BaseModel):
    texts: List[str]


class IndexRequest(BaseModel):
    texts: List[str]
    document_id: Optional[str] = None
    filename: Optional[str] = None
    scope_key: str = "global"
    owner_username: Optional[str] = None
    knowledge_base: str = "global"


class SearchRequest(BaseModel):
    query: str
    top_k: int = 5
    scope_keys: List[str] = ["global"]


def normalize_scope_key(scope_key: str | None):
    scope = (scope_key or "global").strip()
    return scope or "global"


def scope_filter(scope_keys: List[str] | None = None):
    scopes = [normalize_scope_key(scope) for scope in (scope_keys or ["global"])]
    should = [
        FieldCondition(
            key="scope_key",
            match=MatchAny(any=scopes)
        )
    ]

    if "global" in scopes:
        should.append(IsEmptyCondition(is_empty={"key": "scope_key"}))

    return Filter(
        must_not=[
            FieldCondition(
                key="is_deleted",
                match=MatchValue(value=True)
            )
        ],
        should=should
    )


def active_filter():
    return Filter(
        must_not=[
            FieldCondition(
                key="is_deleted",
                match=MatchValue(value=True)
            )
        ]
    )


def document_scope_filter(document_id: str, scope_key: str | None = None):
    must = [
        FieldCondition(
            key="document_id",
            match=MatchValue(value=document_id)
        )
    ]

    scope = normalize_scope_key(scope_key)
    should = [
        FieldCondition(
            key="scope_key",
            match=MatchValue(value=scope)
        )
    ]

    if scope == "global":
        should.append(IsEmptyCondition(is_empty={"key": "scope_key"}))

    return Filter(must=must, should=should)


# =========================
# Startup
# =========================

def ensure_collection():
    init_collection(get_vector_size())


@app.on_event("startup")
def startup():
    ensure_collection()


# =========================
# Health
# =========================

@app.get("/health")
def health():
    return {"status": "ok"}


# =========================
# Embed
# =========================

@app.post("/embed")
async def embed(req: EmbedRequest):
    vectors = await embed_texts_async(req.texts)
    return {"embeddings": vectors}

# =========================
# Document_id
# =========================

@app.get("/documents")
def list_documents(scope_key: Optional[str] = None, owner_username: Optional[str] = None, all_scopes: bool = False):
    if not collection_exists():
        return []

    scopes = None
    if scope_key:
        scopes = [scope_key]
    elif owner_username:
        scopes = ["global", f"user:{owner_username}"]

    scroll = client.scroll(
        collection_name=COLLECTION_NAME,
        limit=10000,
        with_payload=True,
        with_vectors=False,
        scroll_filter=active_filter() if all_scopes else scope_filter(scopes)
    )

    docs = defaultdict(lambda: {"filename": "", "chunks": 0})

    for point in scroll[0]:

        doc_id = point.payload.get("document_id")
        if not doc_id:
            continue

        filename = point.payload.get("filename")
        point_scope = normalize_scope_key(point.payload.get("scope_key"))

        docs[doc_id]["filename"] = filename
        docs[doc_id]["chunks"] += 1
        docs[doc_id]["scope_key"] = point_scope
        docs[doc_id]["owner_username"] = point.payload.get("owner_username")
        docs[doc_id]["knowledge_base"] = point.payload.get("knowledge_base", "global" if point_scope == "global" else "personal")

    return [
        {
            "document_id": doc_id,
            "filename": data["filename"],
            "chunks": data["chunks"],
            "scope_key": data["scope_key"],
            "owner_username": data["owner_username"],
            "knowledge_base": data["knowledge_base"]
        }
        for doc_id, data in docs.items()
    ]



# =========================
# SOFT DELETE
# =========================

@app.post("/documents/{document_id}/delete")
def soft_delete(document_id: str, scope_key: Optional[str] = None):
    client.set_payload(
        collection_name=COLLECTION_NAME,
        payload={"is_deleted": True},
        points=document_scope_filter(document_id, scope_key)
    )

    return {"status": "soft_deleted"}

# =========================
# Index (IDEMPOTENT)
# =========================

@app.post("/index")
async def index(req: IndexRequest):

    if not req.document_id:
        return {"error": "document_id is required for indexing"}

    scope = normalize_scope_key(req.scope_key)
    vectors = await embed_texts_async(req.texts)
    ensure_collection()

    # 🔥 Удаляем старые chunks документа
    await asyncio.to_thread(
        client.delete,
        collection_name=COLLECTION_NAME,
        points_selector=document_scope_filter(req.document_id, scope)
    )

    points = []

    for text, vector in zip(req.texts, vectors):

        # 🔥 UUID вместо строки
        point_id = str(uuid.uuid4())

        points.append({
            "id": point_id,
            "vector": vector,
            "payload": {
                "text": text,
                "document_id": req.document_id,
                "filename": req.filename,
                "scope_key": scope,
                "owner_username": req.owner_username,
                "knowledge_base": req.knowledge_base
            }
        })

    await asyncio.to_thread(
        client.upsert,
        collection_name=COLLECTION_NAME,
        points=points
    )

    return {
        "status": "indexed",
        "count": len(points),
        "document_id": req.document_id,
        "scope_key": scope
    }


@app.post("/scope/{scope_key}/delete")
def soft_delete_scope(scope_key: str):
    client.set_payload(
        collection_name=COLLECTION_NAME,
        payload={"is_deleted": True},
        points=Filter(
            must=[
                FieldCondition(
                    key="scope_key",
                    match=MatchValue(value=normalize_scope_key(scope_key))
                )
            ]
        )
    )

    return {"status": "scope_soft_deleted", "scope_key": normalize_scope_key(scope_key)}

# =========================
# Reindex
# =========================

@app.post("/documents/{document_id}/reindex")
def reindex(document_id: str):
    # просто триггер повторного index через ingestion-service
    return {"status": "use upload again to reindex"}


# =========================
# Search
# =========================

@app.post("/search")
async def search(req: SearchRequest):

    top_k = max(1, min(req.top_k, 30))
    query_vector = (await embed_texts_async([req.query]))[0]
    ensure_collection()

    results = await asyncio.to_thread(
        client.query_points,
        collection_name=COLLECTION_NAME,
        query=query_vector,
        limit=top_k,
        with_payload=True,
        with_vectors=False,
        query_filter=scope_filter(req.scope_keys)
    )

    return {
        "results": [
            {
                "text": point.payload.get("text"),
                "score": point.score,
                "document_id": point.payload.get("document_id"),
                "filename": point.payload.get("filename"),
                "scope_key": normalize_scope_key(point.payload.get("scope_key")),
                "owner_username": point.payload.get("owner_username"),
                "knowledge_base": point.payload.get("knowledge_base", "global")
            }
            for point in results.points
        ]
    }
