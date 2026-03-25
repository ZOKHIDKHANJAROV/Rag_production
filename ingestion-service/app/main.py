from fastapi import FastAPI, UploadFile, File
import requests
import hashlib
from pypdf import PdfReader
from docx import Document
from io import BytesIO

app = FastAPI(title="Ingestion Service")

VECTOR_SERVICE_URL = "http://embedding-service:8001"


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
    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end].strip()

        if chunk:
            chunks.append(chunk)

        start += chunk_size - overlap

    return chunks


@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):

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

        elif filename.endswith(".txt"):
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
        response = requests.post(
            f"{VECTOR_SERVICE_URL}/index",
            json={
                "texts": chunks,
                "document_id": file_hash,
                "filename": file.filename
            }
        )

        if response.status_code != 200:
            return {"error": "Vector service failed", "details": response.text}

    except Exception as e:
        return {"error": f"Vector service unreachable: {str(e)}"}

    return {
        "status": "indexed",
        "document_id": file_hash,
        "chunks": len(chunks)
    }
