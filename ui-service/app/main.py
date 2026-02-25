from fastapi import FastAPI, Request, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import requests
import logging
import os

# ====== LOGGING ======
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(title="RAG UI Service")

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# ====== CONFIG FROM ENV ======
RAG_URL = os.getenv("RAG_SERVICE_URL", "http://rag-service:8003/ask")
INGEST_URL = os.getenv("INGESTION_SERVICE_URL", "http://ingestion-service:8004/upload")
EMBED_URL = os.getenv("EMBEDDING_SERVICE_URL", "http://embedding-service:8001/documents")
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", "50")) * 1024 * 1024

@app.get("/health")
def health():
    try:
        requests.get(f"{RAG_URL.replace('/ask', '')}/health", timeout=5)
        return {"status": "ok", "service": "ui-service"}
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        raise HTTPException(status_code=503, detail="Service unhealthy")


@app.get("/", response_class=HTMLResponse)
def chat_page(request: Request):
    logger.debug("Chat page requested")
    return templates.TemplateResponse("chat.html", {"request": request})


@app.post("/ask")
def ask(question: str = Form(...)):
    try:
        if not question or not question.strip():
            raise HTTPException(status_code=400, detail="Question cannot be empty")
        
        logger.info(f"Processing question: {question[:100]}...")
        
        response = requests.post(
            RAG_URL,
            json={"question": question, "top_k": 3}
        )
        response.raise_for_status()
        result = response.json()
        logger.debug("Question processed successfully")
        return JSONResponse(content=result)
    except requests.exceptions.RequestException as e:
        logger.error(f"RAG service error: {str(e)}")
        raise HTTPException(status_code=502, detail="RAG service unavailable")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ask failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")


@app.post("/upload")
def upload(file: UploadFile = File(...)):
    try:
        if not file.filename:
            raise HTTPException(status_code=400, detail="No file provided")
        
        logger.info(f"Uploading file: {file.filename}")
        
        file_bytes = file.file.read()
        
        if len(file_bytes) > MAX_FILE_SIZE:
            logger.warning(f"File too large: {len(file_bytes)} bytes")
            raise HTTPException(status_code=413, detail=f"File too large (max {MAX_FILE_SIZE / 1024 / 1024}MB)")
        
        files = {
            "file": (file.filename, file_bytes, file.content_type)
        }

        response = requests.post(INGEST_URL, files=files)
        response.raise_for_status()
        result = response.json()
        logger.info(f"File uploaded successfully: {file.filename}")
        return JSONResponse(content=result)
    except requests.exceptions.RequestException as e:
        logger.error(f"Ingestion service error: {str(e)}")
        raise HTTPException(status_code=502, detail="Ingestion service unavailable")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Upload failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


@app.get("/documents")
def documents():
    try:
        logger.debug("Fetching documents list")
        resp = requests.get(EMBED_URL)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Embedding service error: {str(e)}")
        raise HTTPException(status_code=502, detail="Embedding service unavailable")
    except Exception as e:
        logger.error(f"Get documents failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch documents: {str(e)}")
