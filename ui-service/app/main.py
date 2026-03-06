from fastapi import FastAPI, Request, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

import requests
import logging
import os
import uuid

# =========================
# LOGGING
# =========================

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger("ui-service")

# =========================
# FASTAPI APP
# =========================

app = FastAPI(title="RAG UI Service")

templates = Jinja2Templates(directory="templates")

app.mount("/static", StaticFiles(directory="static"), name="static")

# =========================
# CONFIG
# =========================

RAG_URL = os.getenv(
    "RAG_SERVICE_URL",
    "http://rag-service:8003/ask"
)

INGEST_URL = os.getenv(
    "INGESTION_SERVICE_URL",
    "http://ingestion-service:8004/upload"
)

EMBED_URL = os.getenv(
    "EMBEDDING_SERVICE_URL",
    "http://embedding-service:8001/documents"
)

MAX_FILE_SIZE = int(
    os.getenv("MAX_FILE_SIZE", "50")
) * 1024 * 1024

REQUEST_TIMEOUT = int(
    os.getenv("REQUEST_TIMEOUT", "300")
)

# =========================
# HEALTH CHECK
# =========================

@app.get("/health")
def health():

    try:

        rag_health = requests.get(
            RAG_URL.replace("/ask", "") + "/health",
            timeout=5
        )

        rag_health.raise_for_status()

        return {
            "status": "ok",
            "service": "ui-service"
        }

    except Exception as e:

        logger.error(f"Health check failed: {str(e)}")

        raise HTTPException(
            status_code=503,
            detail="Service unhealthy"
        )

# =========================
# CHAT PAGE
# =========================

@app.get("/", response_class=HTMLResponse)
def chat_page(request: Request):

    logger.debug("Rendering chat UI")

    return templates.TemplateResponse(
        "chat.html",
        {"request": request}
    )

# =========================
# ASK QUESTION
# =========================

@app.post("/ask")
def ask(
    question: str = Form(...),
    session_id: str = Form(None)
):

    try:

        if not question.strip():
            raise HTTPException(
                status_code=400,
                detail="Question cannot be empty"
            )

        # create session if missing
        if not session_id:
            session_id = str(uuid.uuid4())

        logger.info(
            f"Question received | session={session_id} | q={question[:80]}"
        )

        payload = {
            "question": question,
            "session_id": session_id,
            "top_k": 3
        }

        response = requests.post(
            RAG_URL,
            json=payload,
            timeout=REQUEST_TIMEOUT
        )

        response.raise_for_status()

        result = response.json()

        logger.info(
            f"Answer generated | session={session_id}"
        )

        return JSONResponse(content=result)

    except requests.exceptions.RequestException as e:

        logger.error(f"RAG service error: {str(e)}")

        raise HTTPException(
            status_code=502,
            detail="RAG service unavailable"
        )

    except HTTPException:
        raise

    except Exception as e:

        logger.error(
            f"Ask failed: {str(e)}",
            exc_info=True
        )

        raise HTTPException(
            status_code=500,
            detail="Internal server error"
        )

# =========================
# FILE UPLOAD
# =========================

@app.post("/upload")
def upload(file: UploadFile = File(...)):

    try:

        if not file.filename:

            raise HTTPException(
                status_code=400,
                detail="No file provided"
            )

        logger.info(f"Uploading file: {file.filename}")

        file_bytes = file.file.read()

        if len(file_bytes) > MAX_FILE_SIZE:

            logger.warning(
                f"File too large: {file.filename}"
            )

            raise HTTPException(
                status_code=413,
                detail=f"File too large (max {MAX_FILE_SIZE / 1024 / 1024}MB)"
            )

        files = {
            "file": (
                file.filename,
                file_bytes,
                file.content_type
            )
        }

        response = requests.post(
            INGEST_URL,
            files=files,
            timeout=REQUEST_TIMEOUT
        )

        response.raise_for_status()

        result = response.json()

        logger.info(
            f"File uploaded successfully: {file.filename}"
        )

        return JSONResponse(content=result)

    except requests.exceptions.RequestException as e:

        logger.error(
            f"Ingestion service error: {str(e)}"
        )

        raise HTTPException(
            status_code=502,
            detail="Ingestion service unavailable"
        )

    except HTTPException:
        raise

    except Exception as e:

        logger.error(
            f"Upload failed: {str(e)}",
            exc_info=True
        )

        raise HTTPException(
            status_code=500,
            detail="Upload failed"
        )

# =========================
# DOCUMENTS LIST
# =========================

@app.get("/documents")
def documents():

    try:

        logger.debug("Fetching documents")

        resp = requests.get(
            EMBED_URL,
            timeout=REQUEST_TIMEOUT
        )

        resp.raise_for_status()

        return resp.json()

    except requests.exceptions.RequestException as e:

        logger.error(
            f"Embedding service error: {str(e)}"
        )

        raise HTTPException(
            status_code=502,
            detail="Embedding service unavailable"
        )

    except Exception as e:

        logger.error(
            f"Get documents failed: {str(e)}",
            exc_info=True
        )

        raise HTTPException(
            status_code=500,
            detail="Failed to fetch documents"
        )