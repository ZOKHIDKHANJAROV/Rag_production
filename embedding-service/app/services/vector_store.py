import asyncio
from collections import defaultdict
import uuid

from qdrant_client.models import PointStruct

from app.model import embed_texts, get_vector_size
from app.qdrant_client import (
    COLLECTION_NAME,
    LEXICAL_COLLECTION_NAME,
    LEXICAL_VECTOR_NAME,
    client,
    collection_exists,
    init_collection,
    init_lexical_collection,
)
from app.schemas import IndexRequest
from app.services.filters import (
    active_filter,
    document_scope_filter,
    normalize_scope_key,
    scope_filter,
)
from app.services.lexical import lexical_vector


class VectorStore:
    """Coordinates dense and sparse Qdrant collections behind one API."""

    def __init__(self, concurrency: int) -> None:
        self._embedding_semaphore = asyncio.Semaphore(concurrency)

    def initialize(self) -> None:
        init_collection(get_vector_size())
        init_lexical_collection()

    async def embed(self, texts: list[str]) -> list[list[float]]:
        async with self._embedding_semaphore:
            return await asyncio.to_thread(embed_texts, texts)

    async def list_documents(
        self,
        scope_key: str | None = None,
        owner_username: str | None = None,
        all_scopes: bool = False,
    ) -> list[dict]:
        if not collection_exists():
            return []

        scopes = [scope_key] if scope_key else (
            ["global", f"user:{owner_username}"] if owner_username else None
        )
        scroll = await asyncio.to_thread(
            client.scroll,
            collection_name=COLLECTION_NAME,
            limit=10000,
            with_payload=True,
            with_vectors=False,
            scroll_filter=active_filter() if all_scopes else scope_filter(scopes),
        )
        documents = defaultdict(lambda: {"filename": "", "chunks": 0})
        for point in scroll[0]:
            payload = point.payload
            document_id = payload.get("document_id")
            if not document_id:
                continue
            documents[document_id].update(
                {
                    "filename": payload.get("filename"),
                    "title": payload.get("title"),
                    "document_date": payload.get("document_date"),
                    "document_type": payload.get("document_type"),
                    "uploaded_at": payload.get("uploaded_at"),
                    "scope_key": normalize_scope_key(payload.get("scope_key")),
                    "owner_username": payload.get("owner_username"),
                    "knowledge_base": payload.get(
                        "knowledge_base",
                        "global" if normalize_scope_key(payload.get("scope_key")) == "global" else "personal",
                    ),
                }
            )
            documents[document_id]["chunks"] += 1

        return [
            {"document_id": document_id, **document}
            for document_id, document in documents.items()
        ]

    async def soft_delete_document(self, document_id: str, scope_key: str | None) -> None:
        point_filter = document_scope_filter(document_id, scope_key)
        for collection_name in (COLLECTION_NAME, LEXICAL_COLLECTION_NAME):
            if collection_exists(collection_name):
                await asyncio.to_thread(
                    client.set_payload,
                    collection_name=collection_name,
                    payload={"is_deleted": True},
                    points=point_filter,
                )

    async def index(self, request: IndexRequest) -> dict:
        if not request.document_id:
            return {"error": "document_id is required for indexing"}

        scope = normalize_scope_key(request.scope_key)
        vectors = await self.embed(request.texts)
        self.initialize()
        point_filter = document_scope_filter(request.document_id, scope)
        for collection_name in (COLLECTION_NAME, LEXICAL_COLLECTION_NAME):
            await asyncio.to_thread(
                client.delete,
                collection_name=collection_name,
                points_selector=point_filter,
            )

        dense_points: list[PointStruct] = []
        lexical_points: list[PointStruct] = []
        for index, (text, vector) in enumerate(zip(request.texts, vectors)):
            section = request.sections[index] if request.sections and index < len(request.sections) else None
            payload = {
                "text": text,
                "document_id": request.document_id,
                "filename": request.filename,
                "title": request.title,
                "section": section,
                "document_date": request.document_date,
                "document_type": request.document_type,
                "uploaded_at": request.uploaded_at,
                "scope_key": scope,
                "owner_username": request.owner_username,
                "knowledge_base": request.knowledge_base,
            }
            point_id = str(uuid.uuid4())
            dense_points.append(PointStruct(id=point_id, vector=vector, payload=payload))
            lexical_points.append(
                PointStruct(
                    id=point_id,
                    vector={
                        LEXICAL_VECTOR_NAME: lexical_vector(
                            text,
                            title=request.title,
                            section=section,
                            filename=request.filename,
                        )
                    },
                    payload=payload,
                )
            )

        await asyncio.gather(
            asyncio.to_thread(
                client.upsert,
                collection_name=COLLECTION_NAME,
                points=dense_points,
            ),
            asyncio.to_thread(
                client.upsert,
                collection_name=LEXICAL_COLLECTION_NAME,
                points=lexical_points,
            ),
        )
        return {
            "status": "indexed",
            "count": len(dense_points),
            "document_id": request.document_id,
            "scope_key": scope,
        }

    async def soft_delete_scope(self, scope_key: str) -> dict:
        normalized_scope = normalize_scope_key(scope_key)
        from qdrant_client.models import Filter, FieldCondition, MatchValue

        point_filter = Filter(
            must=[FieldCondition(key="scope_key", match=MatchValue(value=normalized_scope))]
        )
        for collection_name in (COLLECTION_NAME, LEXICAL_COLLECTION_NAME):
            if collection_exists(collection_name):
                await asyncio.to_thread(
                    client.set_payload,
                    collection_name=collection_name,
                    payload={"is_deleted": True},
                    points=point_filter,
                )
        return {"status": "scope_soft_deleted", "scope_key": normalized_scope}

    async def search(self, query: str, top_k: int, scope_keys: list[str]) -> dict:
        self.initialize()
        query_vector = (await self.embed([query]))[0]
        query_filter = scope_filter(scope_keys)
        dense_task = asyncio.to_thread(
            client.query_points,
            collection_name=COLLECTION_NAME,
            query=query_vector,
            limit=top_k,
            with_payload=True,
            with_vectors=False,
            query_filter=query_filter,
        )
        sparse_task = asyncio.to_thread(
            client.query_points,
            collection_name=LEXICAL_COLLECTION_NAME,
            query=lexical_vector(query),
            using=LEXICAL_VECTOR_NAME,
            limit=top_k,
            with_payload=True,
            with_vectors=False,
            query_filter=query_filter,
        )
        dense_response, sparse_response = await asyncio.gather(dense_task, sparse_task)
        dense_results = self._serialize_results(dense_response.points, "dense")
        sparse_results = self._serialize_results(sparse_response.points, "sparse")
        return {
            "results": dense_results + sparse_results,
            "dense_results": dense_results,
            "sparse_results": sparse_results,
        }

    @staticmethod
    def _serialize_results(points, channel: str) -> list[dict]:
        return [
            {
                "text": point.payload.get("text"),
                "score": point.score,
                "document_id": point.payload.get("document_id"),
                "filename": point.payload.get("filename"),
                "title": point.payload.get("title"),
                "section": point.payload.get("section"),
                "document_date": point.payload.get("document_date"),
                "document_type": point.payload.get("document_type"),
                "uploaded_at": point.payload.get("uploaded_at"),
                "scope_key": normalize_scope_key(point.payload.get("scope_key")),
                "owner_username": point.payload.get("owner_username"),
                "knowledge_base": point.payload.get("knowledge_base", "global"),
                "retrieval_channel": channel,
                "retrieval_rank": rank,
            }
            for rank, point in enumerate(points, start=1)
        ]
