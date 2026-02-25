from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Optional
import uuid
from collections import defaultdict
from qdrant_client.models import (
    Filter,
    FieldCondition,
    MatchValue
)

from app.model import embed_texts, VECTOR_SIZE
from app.qdrant_client import client, init_collection, COLLECTION_NAME

app = FastAPI(title="Vector Service")


# =========================
# Request Models
# =========================

class EmbedRequest(BaseModel):
    texts: List[str]


class IndexRequest(BaseModel):
    texts: List[str]
    document_id: Optional[str] = None
    filename: Optional[str] = None


class SearchRequest(BaseModel):
    query: str
    top_k: int = 5


# =========================
# Startup
# =========================

@app.on_event("startup")
def startup():
    init_collection(VECTOR_SIZE)


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
def embed(req: EmbedRequest):
    vectors = embed_texts(req.texts)
    return {"embeddings": vectors}

# =========================
# Document_id
# =========================

@app.get("/documents")
def list_documents():

    scroll = client.scroll(
        collection_name=COLLECTION_NAME,
        limit=10000,
        with_payload=True,
        with_vectors=False,
        scroll_filter=Filter(
            must_not=[
                FieldCondition(
                    key="is_deleted",
                    match=MatchValue(value=True)
                )
            ]
        )
    )

    docs = defaultdict(lambda: {"filename": "", "chunks": 0})

    for point in scroll[0]:

        doc_id = point.payload.get("document_id")
        if not doc_id:
            continue

        filename = point.payload.get("filename")

        docs[doc_id]["filename"] = filename
        docs[doc_id]["chunks"] += 1

    return [
        {
            "document_id": doc_id,
            "filename": data["filename"],
            "chunks": data["chunks"]
        }
        for doc_id, data in docs.items()
    ]



# =========================
# SOFT DELETE
# =========================

@app.post("/documents/{document_id}/delete")
def soft_delete(document_id: str):

    client.set_payload(
        collection_name=COLLECTION_NAME,
        payload={"is_deleted": True},
        points=Filter(
            must=[
                FieldCondition(
                    key="document_id",
                    match=MatchValue(value=document_id)
                )
            ]
        )
    )

    return {"status": "soft_deleted"}

# =========================
# Index (IDEMPOTENT)
# =========================

@app.post("/index")
def index(req: IndexRequest):

    if not req.document_id:
        return {"error": "document_id is required for indexing"}

    vectors = embed_texts(req.texts)

    # 🔥 Удаляем старые chunks документа
    client.delete(
        collection_name=COLLECTION_NAME,
        points_selector=Filter(
            must=[
                FieldCondition(
                    key="document_id",
                    match=MatchValue(value=req.document_id)
                )
            ]
        )
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
                "filename": req.filename
            }
        })

    client.upsert(
        collection_name=COLLECTION_NAME,
        points=points
    )

    return {
        "status": "indexed",
        "count": len(points),
        "document_id": req.document_id
    }

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
def search(req: SearchRequest):

    query_vector = embed_texts([req.query])[0]

    results = client.query_points(
    collection_name=COLLECTION_NAME,
    query=query_vector,
    limit=req.top_k,
    query_filter=Filter(
        must_not=[
            FieldCondition(
                key="is_deleted",
                match=MatchValue(value=True)
            )
        ]
    )
)

    return {
        "results": [
            {
                "text": point.payload.get("text"),
                "score": point.score,
                "document_id": point.payload.get("document_id"),
                "filename": point.payload.get("filename")
            }
            for point in results.points
        ]
    }
