import base64
import os
import re

import fitz
import httpx
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse


app = FastAPI(title="Unlimited OCR Adapter")

OCR_MODEL_URL = os.getenv(
    "OCR_MODEL_URL",
    "http://unlimited-ocr-model:8000/v1/chat/completions",
)
OCR_MODEL_NAME = os.getenv("OCR_MODEL_NAME", "baidu/Unlimited-OCR")
OCR_MAX_PAGES = int(os.getenv("OCR_MAX_PAGES", "20"))
OCR_RENDER_DPI = int(os.getenv("OCR_RENDER_DPI", "150"))
OCR_MAX_TOKENS = int(os.getenv("OCR_MAX_TOKENS", "32768"))
OCR_REQUEST_TIMEOUT = int(os.getenv("OCR_REQUEST_TIMEOUT", "1200"))
INTERNAL_SERVICE_TOKEN = os.getenv("INTERNAL_SERVICE_TOKEN", "")
SERVICE_AUTH_HEADER = "X-Service-Token"

client: httpx.AsyncClient | None = None


@app.middleware("http")
async def require_service_token(request: Request, call_next):
    if request.url.path == "/health":
        return await call_next(request)

    if not INTERNAL_SERVICE_TOKEN:
        return JSONResponse(
            status_code=503,
            content={"detail": "Internal service token is not configured"},
        )

    if request.headers.get(SERVICE_AUTH_HEADER, "") != INTERNAL_SERVICE_TOKEN:
        return JSONResponse(status_code=401, content={"detail": "Invalid internal service token"})

    return await call_next(request)


@app.on_event("startup")
async def startup_event():
    global client
    client = httpx.AsyncClient(
        timeout=httpx.Timeout(OCR_REQUEST_TIMEOUT, connect=10.0),
        limits=httpx.Limits(max_connections=8, max_keepalive_connections=4),
    )


@app.on_event("shutdown")
async def shutdown_event():
    if client:
        await client.aclose()


@app.get("/health")
async def health():
    if client is None:
        raise HTTPException(status_code=503, detail="OCR client is not initialized")

    try:
        response = await client.get(OCR_MODEL_URL.rsplit("/v1/", 1)[0] + "/health", timeout=5.0)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="OCR model is unavailable") from exc

    return {"status": "ok", "service": "ocr-service", "model": OCR_MODEL_NAME}


def clean_ocr_text(text: str):
    references = re.findall(r"<\|ref\|>(.*?)<\|/ref\|>", text or "", flags=re.DOTALL)
    cleaned = "\n\n".join(references) if references else (text or "")
    cleaned = re.sub(r"<\|det\|>.*?<\|/det\|>", "", cleaned, flags=re.DOTALL)
    return cleaned.strip()


def pdf_pages_as_data_urls(file_bytes: bytes):
    document = fitz.open(stream=file_bytes, filetype="pdf")
    try:
        if document.page_count > OCR_MAX_PAGES:
            raise HTTPException(
                status_code=413,
                detail=f"OCR page limit exceeded (max {OCR_MAX_PAGES})",
            )

        matrix = fitz.Matrix(OCR_RENDER_DPI / 72, OCR_RENDER_DPI / 72)
        images = []
        for page in document:
            image_bytes = page.get_pixmap(matrix=matrix, alpha=False).tobytes("png")
            images.append("data:image/png;base64," + base64.b64encode(image_bytes).decode())
        return images
    finally:
        document.close()


def image_as_data_url(file_bytes: bytes, filename: str):
    extension = os.path.splitext(filename)[1].lower().lstrip(".")
    mime = "image/jpeg" if extension in {"jpg", "jpeg"} else f"image/{extension}"
    return "data:" + mime + ";base64," + base64.b64encode(file_bytes).decode()


def build_ocr_payload(image_urls):
    is_multi_page = len(image_urls) > 1
    return {
        "model": OCR_MODEL_NAME,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "<image>Multi page parsing." if is_multi_page else "<image>document parsing.",
                    },
                    *[
                        {"type": "image_url", "image_url": {"url": image_url}}
                        for image_url in image_urls
                    ],
                ],
            }
        ],
        "temperature": 0,
        "max_tokens": OCR_MAX_TOKENS,
        "skip_special_tokens": False,
        "vllm_xargs": {
            "ngram_size": 35,
            "window_size": 1024 if is_multi_page else 128,
        },
    }


@app.post("/extract")
async def extract(file: UploadFile = File(...), filename: str | None = Form(None)):
    if client is None:
        raise HTTPException(status_code=503, detail="OCR client is not initialized")

    source_name = filename or file.filename or "document"
    extension = os.path.splitext(source_name)[1].lower()
    file_bytes = await file.read()

    if not file_bytes:
        raise HTTPException(status_code=400, detail="Empty file")

    if extension == ".pdf":
        image_urls = pdf_pages_as_data_urls(file_bytes)
    elif extension in {".png", ".jpg", ".jpeg", ".webp"}:
        image_urls = [image_as_data_url(file_bytes, source_name)]
    else:
        raise HTTPException(status_code=415, detail="OCR supports PDF and image files")

    try:
        response = await client.post(OCR_MODEL_URL, json=build_ocr_payload(image_urls))
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Unlimited-OCR model is unavailable") from exc

    try:
        raw_text = response.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Invalid OCR model response") from exc

    text = clean_ocr_text(raw_text)
    if not text:
        raise HTTPException(status_code=422, detail="OCR returned no text")

    return {"text": text, "pages": len(image_urls), "engine": "Unlimited-OCR"}
