from fastapi import FastAPI, UploadFile, File, Form, HTTPException
import httpx
import hashlib
import re
from pypdf import PdfReader
from docx import Document
from io import BytesIO
import os

app = FastAPI(title="Ingestion Service")

VECTOR_SERVICE_URL = os.getenv("VECTOR_SERVICE_URL", "http://embedding-service:8001")
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "300"))
HTTP_MAX_CONNECTIONS = int(os.getenv("INGESTION_HTTP_MAX_CONNECTIONS", "100"))
HTTP_MAX_KEEPALIVE = int(os.getenv("INGESTION_HTTP_MAX_KEEPALIVE", "20"))

http_client: httpx.AsyncClient | None = None


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


@app.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    scope_key: str = Form("global"),
    owner_username: str | None = Form(None),
    knowledge_base: str = Form("global")
):

    # 1️⃣ Читаем файл полностью
    file_bytes = await file.read()

    if not file_bytes:
        return {"error": "Empty file"}

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
            return {"error": "Unsupported file type"}

    except Exception as e:
        return {"error": f"Text extraction failed: {str(e)}"}

    if not text.strip():
        return {"error": "No text extracted from file"}

    # 4️⃣ Chunking
    chunks = chunk_text(text)

    if not chunks:
        return {"error": "No chunks generated"}

    # 5️⃣ Отправляем в embedding-service
    try:
        response = await http_client.post(
            f"{VECTOR_SERVICE_URL}/index",
            json={
                "texts": chunks,
                "document_id": file_hash,
                "filename": file.filename,
                "scope_key": scope_key,
                "owner_username": owner_username,
                "knowledge_base": knowledge_base
            },
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
        "owner_username": owner_username
    }
