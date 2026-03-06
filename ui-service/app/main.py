from fastapi import FastAPI, Request, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

import requests
import logging
import os
import uuid
import json
from datetime import datetime
from typing import Optional, Dict, List

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

app = FastAPI(
    title="RAG UI Service",
    description="Advanced RAG System Web Interface",
    version="2.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

templates = Jinja2Templates(directory="templates")

app.mount("/static", StaticFiles(directory="static"), name="static")

# =========================
# SESSION STORAGE (In-memory)
# =========================

sessions: Dict[str, Dict] = {}

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
    "http://embedding-service:8001"
)

MAX_FILE_SIZE = int(
    os.getenv("MAX_FILE_SIZE", "50")
) * 1024 * 1024

REQUEST_TIMEOUT = int(
    os.getenv("REQUEST_TIMEOUT", "300")
)

# Service URLs for health checks
SERVICES = {
    "rag": RAG_URL.replace("/ask", ""),
    "embedding": f"{EMBED_URL}",
    "ingestion": INGEST_URL.replace("/upload", ""),
    "llm": os.getenv("LLM_SERVICE_URL", "http://llm-service:8002"),
    "qdrant": os.getenv("QDRANT_URL", "http://qdrant:6333")
}

# =========================
# HEALTH CHECK
# =========================

@app.get("/health")
def health():
    """Check overall system health"""
    try:
        rag_health = requests.get(
            SERVICES["rag"] + "/health",
            timeout=5
        )
        rag_health.raise_for_status()

        return {
            "status": "ok",
            "service": "ui-service",
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        raise HTTPException(
            status_code=503,
            detail="Service unhealthy"
        )


@app.get("/api/services-status")
def services_status():
    """Get status of all backend services"""
    status = {}
    
    for service_name, service_url in SERVICES.items():
        try:
            response = requests.get(
                f"{service_url}/health",
                timeout=3
            )
            status[service_name] = {
                "status": "healthy" if response.status_code == 200 else "offline",
                "url": service_url
            }
        except Exception as e:
            logger.warning(f"Service {service_name} health check failed: {str(e)}")
            status[service_name] = {
                "status": "offline",
                "error": str(e),
                "url": service_url
            }
    
    return {"services": status, "timestamp": datetime.now().isoformat()}

# =========================
# ASK QUESTION
# =========================

@app.post("/ask")
def ask(
    question: str = Form(...),
    session_id: str = Form(None)
):
    """Ask a question to the RAG system"""
    try:
        if not question.strip():
            raise HTTPException(
                status_code=400,
                detail="Question cannot be empty"
            )

        # Create session if missing
        if not session_id:
            session_id = str(uuid.uuid4())

        # Initialize session if new
        if session_id not in sessions:
            sessions[session_id] = {
                "history": [],
                "created": datetime.now().isoformat(),
                "documents": []
            }

        logger.info(
            f"Question received | session={session_id} | q={question[:80]}"
        )

        payload = {
            "question": question,
            "session_id": session_id,
            "top_k": 5
        }

        response = requests.post(
            RAG_URL,
            json=payload,
            timeout=REQUEST_TIMEOUT
        )

        response.raise_for_status()
        result = response.json()

        # Store in session history
        sessions[session_id]["history"].append({
            "type": "question",
            "content": question,
            "timestamp": datetime.now().isoformat()
        })
        
        sessions[session_id]["history"].append({
            "type": "answer",
            "content": result.get("answer"),
            "sources": result.get("sources", []),
            "timestamp": datetime.now().isoformat()
        })

        logger.info(
            f"Answer generated | session={session_id}"
        )

        return JSONResponse(content={
            **result,
            "session_id": session_id,
            "timestamp": datetime.now().isoformat()
        })

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
def upload(file: UploadFile = File(...), session_id: str = Form(None)):
    """Upload a document to the RAG system"""
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

        # Track uploaded file in session
        if session_id and session_id in sessions:
            sessions[session_id]["documents"].append({
                "filename": file.filename,
                "timestamp": datetime.now().isoformat(),
                "size": len(file_bytes)
            })

        logger.info(
            f"File uploaded successfully: {file.filename}"
        )

        return JSONResponse(content={
            **result,
            "filename": file.filename,
            "size": len(file_bytes),
            "timestamp": datetime.now().isoformat()
        })

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

@app.get("/api/documents")
def documents():
    """Get list of uploaded documents"""
    try:
        logger.debug("Fetching documents")

        resp = requests.get(
            f"{EMBED_URL}/documents",
            timeout=REQUEST_TIMEOUT
        )

        resp.raise_for_status()
        docs = resp.json()

        return {
            "documents": docs if isinstance(docs, list) else docs.get("documents", []),
            "timestamp": datetime.now().isoformat()
        }

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


# =========================
# SESSION MANAGEMENT
# =========================

@app.get("/api/session/{session_id}")
def get_session(session_id: str):
    """Get session details including history"""
    if session_id not in sessions:
        raise HTTPException(
            status_code=404,
            detail="Session not found"
        )
    
    return {
        "session_id": session_id,
        **sessions[session_id],
        "timestamp": datetime.now().isoformat()
    }


@app.post("/api/session/new")
def create_session():
    """Create a new session"""
    session_id = str(uuid.uuid4())
    sessions[session_id] = {
        "history": [],
        "created": datetime.now().isoformat(),
        "documents": []
    }
    
    logger.info(f"New session created: {session_id}")
    
    return {
        "session_id": session_id,
        "created": sessions[session_id]["created"],
        "timestamp": datetime.now().isoformat()
    }


@app.get("/api/session/{session_id}/history")
def get_history(session_id: str):
    """Get chat history for a session"""
    if session_id not in sessions:
        raise HTTPException(
            status_code=404,
            detail="Session not found"
        )
    
    return {
        "session_id": session_id,
        "history": sessions[session_id]["history"],
        "timestamp": datetime.now().isoformat()
    }


@app.delete("/api/session/{session_id}")
def delete_session(session_id: str):
    """Delete a session"""
    if session_id not in sessions:
        raise HTTPException(
            status_code=404,
            detail="Session not found"
        )
    
    del sessions[session_id]
    
    logger.info(f"Session deleted: {session_id}")
    
    return {
        "message": "Session deleted",
        "session_id": session_id,
        "timestamp": datetime.now().isoformat()
    }


@app.get("/api/sessions")
def list_sessions():
    """List all sessions"""
    return {
        "sessions": [
            {
                "session_id": sid,
                **sessions[sid]
            }
            for sid in sessions.keys()
        ],
        "count": len(sessions),
        "timestamp": datetime.now().isoformat()
    }


# =========================
# MAIN PAGE
# =========================

@app.get("/", response_class=HTMLResponse)
def chat_page(request: Request):
    """Render main chat interface"""
    logger.debug("Rendering chat UI")

    return templates.TemplateResponse(
        "chat.html",
        {"request": request}
    )