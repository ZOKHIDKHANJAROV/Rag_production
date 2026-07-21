import httpx
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.services.document_processing import (
    chunk_document,
    chunk_text,
    derive_document_title,
    extract_text_from_docx,
    extract_text_from_pdf,
    normalize_document_date,
    split_document_sections,
)
from app.services.ingestion import DocumentIngestionService


app = FastAPI(title="Ingestion Service")
http_client: httpx.AsyncClient | None = None

# Compatibility constants and helper retained for direct integrations and tests.
OCR_ENABLED = settings.ocr_enabled


def should_use_ocr(filename: str, text: str, scope_key: str, file_size: int) -> bool:
    return (
        OCR_ENABLED
        and filename.lower().endswith((".pdf", ".png", ".jpg", ".jpeg", ".webp"))
        and scope_key.startswith("user:")
        and file_size > 0
        and not text.strip()
    )


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
async def startup_event():
    global http_client
    http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(settings.request_timeout, connect=5.0),
        limits=httpx.Limits(
            max_connections=settings.http_max_connections,
            max_keepalive_connections=settings.http_max_keepalive,
        ),
    )


@app.on_event("shutdown")
async def shutdown_event():
    if http_client:
        await http_client.aclose()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    scope_key: str = Form("global"),
    owner_username: str | None = Form(None),
    knowledge_base: str = Form("global"),
    document_title: str | None = Form(None),
    document_date: str | None = Form(None),
):
    if http_client is None:
        return JSONResponse(
            status_code=503,
            content={"detail": "Ingestion HTTP client is not initialized"},
        )
    service = DocumentIngestionService(settings, http_client)
    return await service.upload(
        await file.read(),
        file.filename or "upload",
        scope_key,
        owner_username,
        knowledge_base,
        document_title,
        document_date,
    )
