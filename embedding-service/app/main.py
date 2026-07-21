from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routes import create_router
from app.core.config import settings
from app.services.vector_store import VectorStore


vector_store = VectorStore(settings.embedding_concurrency)
app = FastAPI(title="Vector Service")


@app.middleware("http")
async def require_service_token(request: Request, call_next):
    if request.url.path == "/health":
        return await call_next(request)
    if not settings.internal_service_token:
        return JSONResponse(
            status_code=503,
            content={"detail": "Internal service token is not configured"},
        )
    if request.headers.get(settings.service_auth_header, "") != settings.internal_service_token:
        return JSONResponse(status_code=401, content={"detail": "Invalid internal service token"})
    return await call_next(request)


@app.on_event("startup")
def startup() -> None:
    vector_store.initialize()


app.include_router(create_router(vector_store))


# Backward-compatible imports for integrations that used these helpers directly.
from app.services.filters import active_filter, document_scope_filter, normalize_scope_key, scope_filter  # noqa: E402
from app.services.lexical import lexical_tokens, lexical_vector  # noqa: E402
