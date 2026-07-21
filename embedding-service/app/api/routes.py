from fastapi import APIRouter, HTTPException, Query

from app.schemas import EmbedRequest, IndexRequest, SearchRequest
from app.services.vector_store import VectorStore


def create_router(vector_store: VectorStore) -> APIRouter:
    router = APIRouter()

    @router.get("/health")
    async def health():
        return {"status": "ok"}

    @router.post("/embed")
    async def embed(request: EmbedRequest):
        return {"embeddings": await vector_store.embed(request.texts)}

    @router.get("/documents")
    async def list_documents(
        scope_key: str | None = None,
        owner_username: str | None = None,
        all_scopes: bool = False,
    ):
        return await vector_store.list_documents(scope_key, owner_username, all_scopes)

    @router.post("/documents/{document_id}/delete")
    async def soft_delete(document_id: str, scope_key: str | None = None):
        await vector_store.soft_delete_document(document_id, scope_key)
        return {"status": "soft_deleted"}

    @router.post("/index")
    async def index(request: IndexRequest):
        result = await vector_store.index(request)
        if result.get("error"):
            raise HTTPException(status_code=400, detail=result["error"])
        return result

    @router.post("/scope/{scope_key}/delete")
    async def soft_delete_scope(scope_key: str):
        return await vector_store.soft_delete_scope(scope_key)

    @router.post("/documents/{document_id}/reindex")
    async def reindex(document_id: str):
        return {"status": "use upload again to reindex"}

    @router.post("/search")
    async def search(request: SearchRequest):
        return await vector_store.search(request.query, request.top_k, request.scope_keys)

    return router
