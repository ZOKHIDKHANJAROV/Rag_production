from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import JSONResponse
import httpx
import hashlib
import re
from pypdf import PdfReader
from docx import Document
from io import BytesIO
import os
from datetime import datetime, timezone
from pathlib import Path

app = FastAPI(title="Ingestion Service")

VECTOR_SERVICE_URL = os.getenv("VECTOR_SERVICE_URL", "http://embedding-service:8001")
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "300"))
HTTP_MAX_CONNECTIONS = int(os.getenv("INGESTION_HTTP_MAX_CONNECTIONS", "100"))
HTTP_MAX_KEEPALIVE = int(os.getenv("INGESTION_HTTP_MAX_KEEPALIVE", "20"))
INTERNAL_SERVICE_TOKEN = os.getenv("INTERNAL_SERVICE_TOKEN", "")
SERVICE_AUTH_HEADER = "X-Service-Token"

http_client: httpx.AsyncClient | None = None


def service_headers():
    return {SERVICE_AUTH_HEADER: INTERNAL_SERVICE_TOKEN} if INTERNAL_SERVICE_TOKEN else {}


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


@app.on_event("startup")
async def startup_event():
    global http_client
    http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(REQUEST_TIMEOUT, connect=5.0),
        limits=httpx.Limits(
            max_connections=HTTP_MAX_CONNECTIONS,
            max_keepalive_connections=HTTP_MAX_KEEPALIVE
        )
    )


@app.on_event("shutdown")
async def shutdown_event():
    if http_client:
        await http_client.aclose()


@app.get("/health")
def health():
    return {"status": "ok"}


# 🔥 PDF extraction через BytesIO
def extract_text_from_pdf(file_bytes: bytes):
    pdf_stream = BytesIO(file_bytes)
    reader = PdfReader(pdf_stream)

    text = ""
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            text += page_text + "\n"

    return text


# 🔥 DOCX extraction через BytesIO
def extract_text_from_docx(file_bytes: bytes):
    doc_stream = BytesIO(file_bytes)
    doc = Document(doc_stream)
    return "\n".join([para.text for para in doc.paragraphs if para.text])


# 🔥 Chunking
def chunk_text(text, chunk_size=800, overlap=100):
    text = re.sub(r"\s+", " ", text).strip()
    paragraphs = [
        paragraph.strip()
        for paragraph in re.split(r"(?:\n\s*){2,}", text)
        if paragraph.strip()
    ]

    if not paragraphs:
        paragraphs = re.split(r"(?<=[.!?])\s+", text)

    chunks = []
    current = ""

    for paragraph in paragraphs:
        sentences = [paragraph]
        if len(paragraph) > chunk_size:
            sentences = re.split(r"(?<=[.!?])\s+", paragraph)

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            if len(sentence) > chunk_size:
                step = max(1, chunk_size - overlap)
                for start in range(0, len(sentence), step):
                    chunk = sentence[start:start + chunk_size].strip()
                    if chunk:
                        chunks.append(chunk)
                current = ""
                continue

            candidate = f"{current} {sentence}".strip()
            if len(candidate) <= chunk_size:
                current = candidate
                continue

            if current:
                chunks.append(current)
            tail = current[-overlap:].strip() if overlap and current else ""
            current = f"{tail} {sentence}".strip()

    if current:
        chunks.append(current)

    return chunks


def derive_document_title(filename: str, text: str):
    for line in text.splitlines()[:80]:
        candidate = line.strip().lstrip("#").strip()
        if 4 <= len(candidate) <= 160:
            return candidate

    return Path(filename).stem.replace("_", " ").replace("-", " ").strip()[:160]


def normalize_document_date(value: str | None):
    if not value:
        return None

    match = re.search(r"\b(\d{4}-\d{2}-\d{2}|\d{2}[./-]\d{2}[./-]\d{4})\b", value)
    if not match:
        return None

    raw_date = match.group(1).replace("/", ".").replace("-", ".")
    for date_format in ("%Y.%m.%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(raw_date, date_format).date().isoformat()
        except ValueError:
            continue
    return None


def split_document_sections(text: str, fallback_title: str):
    sections = []
    current_title = fallback_title
    current_lines = []

    def append_section():
        content = "\n".join(current_lines).strip()
        if content:
            sections.append((current_title, content))

    for line in text.splitlines():
        heading_match = re.match(
            r"^\s*(?:#{1,6}\s+|\d+(?:\.\d+)*[.)]?\s+)(.{3,160})$",
            line,
        )
        if heading_match:
            append_section()
            current_title = heading_match.group(1).strip()
            current_lines = []
        else:
            current_lines.append(line)

    append_section()
    return sections or [(fallback_title, text)]


def chunk_document(text: str, fallback_title: str):
    chunks = []
    sections = []

    for section_title, section_text in split_document_sections(text, fallback_title):
        for chunk in chunk_text(section_text):
            chunks.append(chunk)
            sections.append(section_title)

    return chunks, sections


@app.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    scope_key: str = Form("global"),
    owner_username: str | None = Form(None),
    knowledge_base: str = Form("global"),
    document_title: str | None = Form(None),
    document_date: str | None = Form(None),
):

    # 1️⃣ Читаем файл полностью
    file_bytes = await file.read()

    if not file_bytes:
        raise HTTPException(status_code=400, detail="Empty file")

    # 2️⃣ Hash документа (детерминированный ID)
    file_hash = hashlib.sha256(file_bytes).hexdigest()

    filename = file.filename.lower()

    # 3️⃣ Извлекаем текст
    try:
        if filename.endswith(".pdf"):
            text = extract_text_from_pdf(file_bytes)

        elif filename.endswith(".docx"):
            text = extract_text_from_docx(file_bytes)

        elif filename.endswith((".txt", ".md")):
            text = file_bytes.decode("utf-8", errors="ignore")

        else:
            raise HTTPException(status_code=415, detail="Unsupported file type")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Text extraction failed: {str(e)}")

    if not text.strip():
        raise HTTPException(status_code=422, detail="No text extracted from file")

    # 4️⃣ Chunking
    title = (document_title or derive_document_title(file.filename, text)).strip()[:160]
    document_type = Path(file.filename).suffix.lower().lstrip(".") or "unknown"
    detected_date = normalize_document_date(document_date) or normalize_document_date(
        f"{file.filename}\n{text[:4000]}"
    )
    uploaded_at = datetime.now(timezone.utc).isoformat()
    chunks, sections = chunk_document(text, title)

    if not chunks:
        raise HTTPException(status_code=422, detail="No chunks generated")

    # 5️⃣ Отправляем в embedding-service
    try:
        response = await http_client.post(
            f"{VECTOR_SERVICE_URL}/index",
            json={
                "texts": chunks,
                "document_id": file_hash,
                "filename": file.filename,
                "title": title,
                "sections": sections,
                "document_date": detected_date,
                "document_type": document_type,
                "uploaded_at": uploaded_at,
                "scope_key": scope_key,
                "owner_username": owner_username,
                "knowledge_base": knowledge_base
            },
            headers=service_headers(),
            timeout=REQUEST_TIMEOUT
        )

        response.raise_for_status()

    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=502,
            detail={"error": "Vector service failed", "details": e.response.text}
        )
    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=503,
            detail=f"Vector service unreachable: {str(e)}"
        )

    return {
        "status": "indexed",
        "document_id": file_hash,
        "chunks": len(chunks),
        "scope_key": scope_key,
        "knowledge_base": knowledge_base,
        "owner_username": owner_username,
        "title": title,
        "document_date": detected_date,
        "document_type": document_type,
        "uploaded_at": uploaded_at,
    }
