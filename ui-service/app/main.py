from fastapi import FastAPI, Request, Response, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import httpx
import logging
import os
import uuid
import json
import secrets
import hashlib
import hmac
import base64
import time
import binascii
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Dict, List

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
refresh_tokens: Dict[str, Dict] = {}
user_documents: Dict[str, List[Dict]] = {}

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
    os.getenv("REQUEST_TIMEOUT", "60")
)
UI_HTTP_MAX_CONNECTIONS = int(os.getenv("UI_HTTP_MAX_CONNECTIONS", "200"))
UI_HTTP_MAX_KEEPALIVE = int(os.getenv("UI_HTTP_MAX_KEEPALIVE", "50"))

SECRET_KEY = os.getenv("SECRET_KEY", "change-me")
JWT_ALGORITHM = "HS256"
ACCESS_COOKIE_NAME = os.getenv("ACCESS_COOKIE_NAME", "rag_access")
REFRESH_COOKIE_NAME = os.getenv("REFRESH_COOKIE_NAME", "rag_refresh")
ACCESS_TOKEN_EXPIRE_SECONDS = int(os.getenv("ACCESS_TOKEN_EXPIRE_SECONDS", "900"))
REFRESH_TOKEN_EXPIRE_SECONDS = int(os.getenv("REFRESH_TOKEN_EXPIRE_SECONDS", "604800"))
AUTH_COOKIE_SECURE = os.getenv("AUTH_COOKIE_SECURE", "false").lower() == "true"
LEGACY_AUTH_COOKIE_NAME = "rag_auth"
USERS_FILE = Path(os.getenv("UI_USERS_FILE", "data/users.json"))

# Backward-compatible alias for code that expects the old auth cookie name.
AUTH_COOKIE_NAME = ACCESS_COOKIE_NAME

DEFAULT_USERS = {
    "admin": {"password": "admin123", "role": "admin"},
    "user": {"password": "user123", "role": "user"},
}

ROLE_ADMIN = "admin"
ROLE_USER = "user"
KNOWN_ROLES = {ROLE_ADMIN, ROLE_USER}

ROLE_LABELS = {
    ROLE_ADMIN: "Админ",
    ROLE_USER: "Пользователь",
}

ROLE_PERMISSIONS = {
    ROLE_ADMIN: {
        "view_all_sessions",
        "delete_any_session",
        "view_all_documents",
        "manage_documents",
        "manage_users",
        "view_services",
    },
    ROLE_USER: {
        "view_own_sessions",
        "delete_own_sessions",
        "view_own_documents",
    },
}


class AdminUserUpdate(BaseModel):
    password: str | None = None
    role: str | None = None


class AdminUserCreate(BaseModel):
    username: str
    password: str
    role: str = ROLE_USER


def normalize_role(role: str) -> str:
    normalized = (role or ROLE_USER).strip().lower()
    if normalized not in KNOWN_ROLES:
        logger.warning("Unknown UI role '%s', falling back to '%s'", role, ROLE_USER)
        return ROLE_USER
    return normalized


def normalize_users(users: Dict) -> Dict:
    return {
        username.strip(): {
            "password": data.get("password", ""),
            "role": normalize_role(data.get("role", ROLE_USER))
        }
        for username, data in users.items()
        if username.strip() and data.get("password")
    }


def load_users():
    raw = os.getenv("UI_USERS_JSON")

    users = DEFAULT_USERS

    if raw:
        try:
            users = normalize_users(json.loads(raw))
        except json.JSONDecodeError:
            logger.warning("Invalid UI_USERS_JSON, falling back to default users")

    if USERS_FILE.exists():
        try:
            file_users = normalize_users(json.loads(USERS_FILE.read_text(encoding="utf-8")))
            users = {**users, **file_users}
        except (OSError, json.JSONDecodeError):
            logger.warning("Invalid UI users file '%s', ignoring it", USERS_FILE)

    return users


def save_users():
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    USERS_FILE.write_text(
        json.dumps(USERS, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

USERS = load_users()

# Service URLs for health checks
SERVICES = {
    "rag": RAG_URL.replace("/ask", ""),
    "embedding": f"{EMBED_URL}",
    "ingestion": INGEST_URL.replace("/upload", ""),
    "llm": os.getenv("LLM_SERVICE_URL", "http://llm-service:8002"),
    "qdrant": os.getenv("QDRANT_URL", "http://qdrant:6333")
}

http_client: httpx.AsyncClient | None = None


@app.on_event("startup")
async def startup_event():
    global http_client
    http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(REQUEST_TIMEOUT, connect=5.0),
        limits=httpx.Limits(
            max_connections=UI_HTTP_MAX_CONNECTIONS,
            max_keepalive_connections=UI_HTTP_MAX_KEEPALIVE
        )
    )


@app.on_event("shutdown")
async def shutdown_event():
    if http_client:
        await http_client.aclose()

# =========================
# AUTH
# =========================

def verify_password(plain_password: str, stored_password: str) -> bool:
    return hmac.compare_digest(plain_password, stored_password)


def jwt_b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def jwt_b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def create_jwt(payload: Dict) -> str:
    header = {
        "alg": JWT_ALGORITHM,
        "typ": "JWT",
    }
    encoded_header = jwt_b64encode(json.dumps(header, separators=(",", ":")).encode())
    encoded_payload = jwt_b64encode(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{encoded_header}.{encoded_payload}".encode()
    signature = hmac.new(SECRET_KEY.encode(), signing_input, hashlib.sha256).digest()
    return f"{encoded_header}.{encoded_payload}.{jwt_b64encode(signature)}"


def decode_jwt(token: str, expected_type: str) -> Dict:
    try:
        encoded_header, encoded_payload, encoded_signature = token.split(".")
        signing_input = f"{encoded_header}.{encoded_payload}".encode()
        expected_signature = hmac.new(
            SECRET_KEY.encode(),
            signing_input,
            hashlib.sha256,
        ).digest()
        actual_signature = jwt_b64decode(encoded_signature)
    except (ValueError, json.JSONDecodeError, binascii.Error):
        raise HTTPException(status_code=401, detail="Invalid token")

    if not hmac.compare_digest(actual_signature, expected_signature):
        raise HTTPException(status_code=401, detail="Invalid token signature")

    try:
        header = json.loads(jwt_b64decode(encoded_header))
        payload = json.loads(jwt_b64decode(encoded_payload))
    except (json.JSONDecodeError, binascii.Error):
        raise HTTPException(status_code=401, detail="Invalid token payload")

    if header.get("alg") != JWT_ALGORITHM:
        raise HTTPException(status_code=401, detail="Invalid token algorithm")

    try:
        expires_at = int(payload.get("exp", 0))
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid token expiration")

    now = int(time.time())
    if expires_at < now:
        raise HTTPException(status_code=401, detail="Token expired")

    if payload.get("type") != expected_type:
        raise HTTPException(status_code=401, detail="Invalid token type")

    return payload


def create_access_token(username: str, user: Dict) -> str:
    now = int(time.time())
    session_user = serialize_user(username, user)
    return create_jwt({
        "sub": username,
        "type": "access",
        "role": session_user["role"],
        "role_label": session_user["role_label"],
        "permissions": session_user["permissions"],
        "iat": now,
        "exp": now + ACCESS_TOKEN_EXPIRE_SECONDS,
        "jti": secrets.token_urlsafe(16),
    })


def create_refresh_token(username: str) -> str:
    now = int(time.time())
    jti = secrets.token_urlsafe(32)
    refresh_tokens[jti] = {
        "username": username,
        "expires_at": now + REFRESH_TOKEN_EXPIRE_SECONDS,
    }
    return create_jwt({
        "sub": username,
        "type": "refresh",
        "iat": now,
        "exp": now + REFRESH_TOKEN_EXPIRE_SECONDS,
        "jti": jti,
    })


def rotate_refresh_token(token: str) -> Dict:
    payload = decode_jwt(token, "refresh")
    jti = payload.get("jti")
    username = payload.get("sub")
    stored_token = refresh_tokens.get(jti)
    now = int(time.time())

    if not stored_token or stored_token.get("username") != username:
        raise HTTPException(status_code=401, detail="Refresh token revoked")

    if stored_token.get("expires_at", 0) < now:
        refresh_tokens.pop(jti, None)
        raise HTTPException(status_code=401, detail="Refresh token expired")

    user = USERS.get(username)
    if not user:
        refresh_tokens.pop(jti, None)
        raise HTTPException(status_code=401, detail="Invalid token subject")

    refresh_tokens.pop(jti, None)
    return {
        "user": serialize_user(username, user),
        "access_token": create_access_token(username, user),
        "refresh_token": create_refresh_token(username),
    }


def set_auth_cookies(response: Response, access_token: str, refresh_token: str = None):
    response.set_cookie(
        ACCESS_COOKIE_NAME,
        access_token,
        max_age=ACCESS_TOKEN_EXPIRE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=AUTH_COOKIE_SECURE
    )

    if refresh_token:
        response.set_cookie(
            REFRESH_COOKIE_NAME,
            refresh_token,
            max_age=REFRESH_TOKEN_EXPIRE_SECONDS,
            httponly=True,
            samesite="lax",
            secure=AUTH_COOKIE_SECURE
        )


def clear_auth_cookies(response: Response):
    response.delete_cookie(ACCESS_COOKIE_NAME)
    response.delete_cookie(REFRESH_COOKIE_NAME)
    if LEGACY_AUTH_COOKIE_NAME not in {ACCESS_COOKIE_NAME, REFRESH_COOKIE_NAME}:
        response.delete_cookie(LEGACY_AUTH_COOKIE_NAME)


def user_from_access_payload(payload: Dict) -> Dict:
    username = payload.get("sub")
    if not username or username not in USERS:
        raise HTTPException(status_code=401, detail="Invalid token subject")

    configured_user = serialize_user(username, USERS[username])
    token_role = normalize_role(payload.get("role", configured_user["role"]))

    if token_role != configured_user["role"]:
        raise HTTPException(status_code=401, detail="User role changed")

    return configured_user


def get_current_user(request: Request):
    token = request.cookies.get(ACCESS_COOKIE_NAME)

    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")

    return user_from_access_payload(decode_jwt(token, "access"))


def get_optional_user(request: Request):
    token = request.cookies.get(ACCESS_COOKIE_NAME)
    if not token:
        return None

    try:
        return user_from_access_payload(decode_jwt(token, "access"))
    except HTTPException:
        return None


def refresh_optional_user(request: Request):
    token = request.cookies.get(REFRESH_COOKIE_NAME)
    if not token:
        return None

    try:
        return rotate_refresh_token(token)
    except HTTPException:
        return None


def has_permission(user: Dict, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS.get(user.get("role", ROLE_USER), set())


def is_admin(user: Dict) -> bool:
    return user.get("role") == ROLE_ADMIN


def require_permission(user: Dict, permission: str):
    if not has_permission(user, permission):
        raise HTTPException(status_code=403, detail="Forbidden")


def serialize_user(username: str, user: Dict) -> Dict:
    role = normalize_role(user.get("role", ROLE_USER))
    return {
        "username": username,
        "role": role,
        "role_label": ROLE_LABELS[role],
        "permissions": sorted(ROLE_PERMISSIONS[role]),
    }


def require_session_owner(session_id: str, user: Dict):
    session = sessions.get(session_id)

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if not is_admin(user) and session.get("username") != user["username"]:
        raise HTTPException(status_code=403, detail="Forbidden")

    return session


def rag_session_id(username: str, session_id: str):
    raw = f"{username}:{session_id}"
    return hashlib.sha256(raw.encode()).hexdigest()


def user_scope_key(username: str) -> str:
    return f"user:{username}"


def request_scope_keys(user: Dict) -> List[str]:
    return ["global", user_scope_key(user["username"])]


def validate_scope_access(user: Dict, scope_key: str):
    scope = (scope_key or "global").strip() or "global"

    if is_admin(user):
        return scope

    if scope != user_scope_key(user["username"]):
        raise HTTPException(status_code=403, detail="Forbidden")

    return scope


def validate_registration(username: str, password: str):
    username = username.strip()

    if len(username) < 3 or len(username) > 32:
        raise HTTPException(
            status_code=400,
            detail="Username must be between 3 and 32 characters"
        )

    if not all(char.isalnum() or char in {"_", "-", "."} for char in username):
        raise HTTPException(
            status_code=400,
            detail="Username can contain letters, numbers, dots, dashes and underscores"
        )

    if len(password) < 6:
        raise HTTPException(
            status_code=400,
            detail="Password must be at least 6 characters"
        )

    if username in USERS:
        raise HTTPException(status_code=409, detail="Username already exists")

    return username


def render_login_page(
    request: Request,
    mode: str = "login",
    error: str = None,
    message: str = None,
    status_code: int = 200
):
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "auth_mode": mode,
            "auth_error": error,
            "auth_message": message,
        },
        status_code=status_code
    )


@app.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...)
):
    username = username.strip()
    user = USERS.get(username)

    if not user or not verify_password(password, user["password"]):
        return render_login_page(
            request,
            mode="login",
            error="Неверное имя пользователя или пароль",
            status_code=401
        )

    access_token = create_access_token(username, user)
    refresh_token = create_refresh_token(username)

    response = RedirectResponse(url="/", status_code=303)
    set_auth_cookies(response, access_token, refresh_token)
    return response


@app.post("/register")
def register(
    request: Request,
    username: str = Form(...),
    password: str = Form(...)
):
    try:
        username = validate_registration(username, password)
    except HTTPException as exc:
        return render_login_page(
            request,
            mode="register",
            error=str(exc.detail),
            status_code=exc.status_code
        )

    USERS[username] = {
        "password": password,
        "role": ROLE_USER,
    }

    try:
        save_users()
    except OSError:
        USERS.pop(username, None)
        logger.exception("Failed to save registered UI user")
        return render_login_page(
            request,
            mode="register",
            error="Не удалось сохранить пользователя. Попробуйте еще раз.",
            status_code=500
        )

    access_token = create_access_token(username, USERS[username])
    refresh_token = create_refresh_token(username)

    response = RedirectResponse(url="/", status_code=303)
    set_auth_cookies(response, access_token, refresh_token)
    return response


@app.post("/refresh")
def refresh(request: Request):
    token = request.cookies.get(REFRESH_COOKIE_NAME)

    if not token:
        raise HTTPException(status_code=401, detail="Refresh token required")

    rotated = rotate_refresh_token(token)

    response = JSONResponse(content={
        "user": rotated["user"],
        "timestamp": datetime.now().isoformat()
    })
    set_auth_cookies(response, rotated["access_token"], rotated["refresh_token"])
    return response


@app.post("/logout")
def logout(request: Request):
    token = request.cookies.get(REFRESH_COOKIE_NAME)

    if token:
        try:
            payload = decode_jwt(token, "refresh")
            refresh_tokens.pop(payload.get("jti"), None)
        except HTTPException:
            pass

    response = RedirectResponse(url="/", status_code=303)
    clear_auth_cookies(response)
    return response


@app.get("/api/me")
def me(request: Request):
    user = get_current_user(request)
    return user

# =========================
# HEALTH CHECK
# =========================

@app.get("/health")
async def health():
    """Check overall system health"""
    try:
        rag_health = await http_client.get(
            SERVICES["rag"] + "/health",
            timeout=5
        )
        rag_health.raise_for_status()

        return {
            "status": "ok",
            "service": "ui-service",
            "timestamp": datetime.now().isoformat()
        }

    except (httpx.HTTPError, RuntimeError) as e:
        logger.error(f"Health check failed: {str(e)}")
        raise HTTPException(
            status_code=503,
            detail="Service unhealthy"
        )


@app.get("/api/services-status")
async def services_status(request: Request):
    """Get status of all backend services"""
    user = get_current_user(request)
    require_permission(user, "view_services")
    status = {}
    
    async def check_service(service_name: str, service_url: str):
        try:
            response = await http_client.get(
                f"{service_url}/health",
                timeout=3
            )
            return service_name, {
                "status": "healthy" if response.status_code == 200 else "offline",
                "url": service_url
            }
        except Exception as e:
            logger.warning(f"Service {service_name} health check failed: {str(e)}")
            return service_name, {
                "status": "offline",
                "error": str(e),
                "url": service_url
            }

    checks = await asyncio.gather(
        *(check_service(name, url) for name, url in SERVICES.items())
    )
    status = dict(checks)
    
    return {"services": status, "timestamp": datetime.now().isoformat()}

# =========================
# ASK QUESTION
# =========================

@app.post("/ask")
async def ask(
    request: Request,
    question: str = Form(...),
    session_id: str = Form(None)
):
    """Ask a question to the RAG system"""
    try:
        user = get_current_user(request)

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
                "username": user["username"],
                "history": [],
                "created": datetime.now().isoformat(),
                "documents": []
            }
        else:
            require_session_owner(session_id, user)

        logger.info(
            f"Question received | user={user['username']} | session={session_id} | q={question[:80]}"
        )

        payload = {
            "question": question,
            "session_id": rag_session_id(user["username"], session_id),
            "top_k": 5,
            "scope_keys": request_scope_keys(user)
        }

        response = await http_client.post(
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

    except httpx.HTTPError as e:
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
async def upload(
    request: Request,
    file: UploadFile = File(...),
    session_id: str = Form(None),
    scope_key: str = Form(None)
):
    """Upload a document to the RAG system"""
    try:
        user = get_current_user(request)

        if not file.filename:
            raise HTTPException(
                status_code=400,
                detail="No file provided"
            )

        logger.info(f"Uploading file: {file.filename} | user={user['username']}")

        file_bytes = await file.read()

        if len(file_bytes) > MAX_FILE_SIZE:
            logger.warning(
                f"File too large: {file.filename}"
            )
            raise HTTPException(
                status_code=413,
                detail=f"File too large (max {MAX_FILE_SIZE / 1024 / 1024}MB)"
            )

        selected_scope = scope_key or user_scope_key(user["username"])
        selected_scope = validate_scope_access(user, selected_scope)
        knowledge_base = "global" if selected_scope == "global" else "personal"
        owner_username = None if selected_scope == "global" else selected_scope.replace("user:", "", 1)

        files = {
            "file": (
                file.filename,
                file_bytes,
                file.content_type
            )
        }
        data = {
            "scope_key": selected_scope,
            "knowledge_base": knowledge_base,
            "owner_username": owner_username or ""
        }

        response = await http_client.post(
            INGEST_URL,
            files=files,
            data=data,
            timeout=REQUEST_TIMEOUT
        )

        response.raise_for_status()
        result = response.json()

        # Track uploaded file in session
        document_entry = {
            "filename": file.filename,
            "document_id": result.get("document_id"),
            "chunks": result.get("chunks"),
            "scope_key": result.get("scope_key", selected_scope),
            "knowledge_base": result.get("knowledge_base", knowledge_base),
            "owner_username": result.get("owner_username", owner_username),
            "timestamp": datetime.now().isoformat(),
            "size": len(file_bytes)
        }

        user_documents.setdefault(user["username"], []).append(document_entry)

        if session_id and session_id in sessions:
            session = require_session_owner(session_id, user)
            session["documents"].append(document_entry)

        logger.info(
            f"File uploaded successfully: {file.filename}"
        )

        return JSONResponse(content={
            **result,
            "filename": file.filename,
            "size": len(file_bytes),
            "timestamp": datetime.now().isoformat()
        })

    except httpx.HTTPError as e:
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
async def documents(request: Request):
    """Get list of uploaded documents"""
    try:
        user = get_current_user(request)
        logger.debug("Fetching documents")

        params = {"all_scopes": "true"} if has_permission(user, "view_all_documents") else {"owner_username": user["username"]}

        resp = await http_client.get(
            f"{EMBED_URL}/documents",
            params=params,
            timeout=REQUEST_TIMEOUT
        )

        resp.raise_for_status()
        docs = resp.json()

        return {
            "documents": docs if isinstance(docs, list) else docs.get("documents", []),
            "timestamp": datetime.now().isoformat()
        }

    except httpx.HTTPError as e:
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
def get_session(request: Request, session_id: str):
    """Get session details including history"""
    user = get_current_user(request)
    session = require_session_owner(session_id, user)
    
    return {
        "session_id": session_id,
        **session,
        "timestamp": datetime.now().isoformat()
    }


@app.post("/api/session/new")
def create_session(request: Request):
    """Create a new session"""
    user = get_current_user(request)
    session_id = str(uuid.uuid4())
    sessions[session_id] = {
        "username": user["username"],
        "history": [],
        "created": datetime.now().isoformat(),
        "documents": []
    }
    
    logger.info(f"New session created: {session_id} | user={user['username']}")
    
    return {
        "session_id": session_id,
        "created": sessions[session_id]["created"],
        "timestamp": datetime.now().isoformat()
    }


@app.get("/api/session/{session_id}/history")
def get_history(request: Request, session_id: str):
    """Get chat history for a session"""
    user = get_current_user(request)
    session = require_session_owner(session_id, user)
    
    return {
        "session_id": session_id,
        "history": session["history"],
        "timestamp": datetime.now().isoformat()
    }


@app.delete("/api/session/{session_id}")
def delete_session(request: Request, session_id: str):
    """Delete a session"""
    user = get_current_user(request)
    require_session_owner(session_id, user)
    
    del sessions[session_id]
    
    logger.info(f"Session deleted: {session_id}")
    
    return {
        "message": "Session deleted",
        "session_id": session_id,
        "timestamp": datetime.now().isoformat()
    }


@app.get("/api/sessions")
def list_sessions(request: Request):
    """List all sessions"""
    user = get_current_user(request)

    visible_sessions = {
        sid: session
        for sid, session in sessions.items()
        if is_admin(user) or session.get("username") == user["username"]
    }

    return {
        "sessions": [
            {
                "session_id": sid,
                **visible_sessions[sid]
            }
            for sid in visible_sessions.keys()
        ],
        "count": len(visible_sessions),
        "timestamp": datetime.now().isoformat()
    }


# =========================
# ADMIN
# =========================

@app.get("/api/admin/users")
def admin_list_users(request: Request):
    user = get_current_user(request)
    require_permission(user, "manage_users")

    return {
        "users": [
            {
                **serialize_user(username, data),
                "sessions": sum(1 for session in sessions.values() if session.get("username") == username),
                "documents": len(user_documents.get(username, [])),
            }
            for username, data in sorted(USERS.items())
        ],
        "timestamp": datetime.now().isoformat()
    }


@app.post("/api/admin/users")
def admin_create_user(request: Request, payload: AdminUserCreate):
    user = get_current_user(request)
    require_permission(user, "manage_users")

    username = validate_registration(payload.username, payload.password)
    USERS[username] = {
        "password": payload.password,
        "role": normalize_role(payload.role),
    }
    save_users()

    return {
        "user": serialize_user(username, USERS[username]),
        "timestamp": datetime.now().isoformat()
    }


@app.patch("/api/admin/users/{username}")
def admin_update_user(request: Request, username: str, payload: AdminUserUpdate):
    user = get_current_user(request)
    require_permission(user, "manage_users")

    if username not in USERS:
        raise HTTPException(status_code=404, detail="User not found")

    if payload.password is not None:
        if len(payload.password) < 6:
            raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
        USERS[username]["password"] = payload.password

    if payload.role is not None:
        USERS[username]["role"] = normalize_role(payload.role)

    save_users()

    return {
        "user": serialize_user(username, USERS[username]),
        "timestamp": datetime.now().isoformat()
    }


@app.delete("/api/admin/users/{username}")
async def admin_delete_user(request: Request, username: str):
    user = get_current_user(request)
    require_permission(user, "manage_users")

    if username == user["username"]:
        raise HTTPException(status_code=400, detail="Admin cannot delete own account")

    if username not in USERS:
        raise HTTPException(status_code=404, detail="User not found")

    USERS.pop(username)
    save_users()

    for sid in [sid for sid, session in sessions.items() if session.get("username") == username]:
        sessions.pop(sid, None)

    user_documents.pop(username, None)
    for token_id, token in list(refresh_tokens.items()):
        if token.get("username") == username:
            refresh_tokens.pop(token_id, None)

    try:
        await http_client.post(
            f"{EMBED_URL}/scope/{user_scope_key(username)}/delete",
            timeout=REQUEST_TIMEOUT
        )
    except httpx.HTTPError:
        logger.warning("Failed to delete vector scope for user '%s'", username)

    return {
        "status": "deleted",
        "username": username,
        "timestamp": datetime.now().isoformat()
    }


@app.get("/api/admin/databases")
async def admin_databases(request: Request):
    user = get_current_user(request)
    require_permission(user, "manage_documents")

    resp = await http_client.get(
        f"{EMBED_URL}/documents",
        params={"all_scopes": "true"},
        timeout=REQUEST_TIMEOUT
    )
    resp.raise_for_status()
    documents = resp.json()
    if not isinstance(documents, list):
        documents = documents.get("documents", [])

    counts = {"global": 0}
    for username in USERS:
        counts[user_scope_key(username)] = 0

    for doc in documents:
        scope = doc.get("scope_key") or "global"
        counts[scope] = counts.get(scope, 0) + 1

    return {
        "databases": [
            {
                "scope_key": "global",
                "name": "Основная база",
                "type": "global",
                "owner_username": None,
                "documents": counts.get("global", 0),
            },
            *[
                {
                    "scope_key": user_scope_key(username),
                    "name": f"Личная база: {username}",
                    "type": "personal",
                    "owner_username": username,
                    "documents": counts.get(user_scope_key(username), 0),
                }
                for username in sorted(USERS)
            ]
        ],
        "timestamp": datetime.now().isoformat()
    }


@app.get("/api/admin/documents")
async def admin_documents(request: Request, scope_key: str = None):
    user = get_current_user(request)
    require_permission(user, "manage_documents")

    params = {"all_scopes": "true"} if not scope_key else {"scope_key": scope_key}
    resp = await http_client.get(
        f"{EMBED_URL}/documents",
        params=params,
        timeout=REQUEST_TIMEOUT
    )
    resp.raise_for_status()

    docs = resp.json()
    return {
        "documents": docs if isinstance(docs, list) else docs.get("documents", []),
        "timestamp": datetime.now().isoformat()
    }


@app.delete("/api/admin/documents/{document_id}")
async def admin_delete_document(request: Request, document_id: str, scope_key: str):
    user = get_current_user(request)
    require_permission(user, "manage_documents")

    resp = await http_client.post(
        f"{EMBED_URL}/documents/{document_id}/delete",
        params={"scope_key": scope_key},
        timeout=REQUEST_TIMEOUT
    )
    resp.raise_for_status()

    return {
        "status": "deleted",
        "document_id": document_id,
        "scope_key": scope_key,
        "timestamp": datetime.now().isoformat()
    }


# =========================
# MAIN PAGE
# =========================

@app.get("/", response_class=HTMLResponse)
def chat_page(request: Request):
    """Render main chat interface"""
    logger.debug("Rendering chat UI")
    user = get_optional_user(request)

    if not user:
        rotated = refresh_optional_user(request)
        if rotated:
            response = templates.TemplateResponse(
                "chat.html",
                {
                    "request": request,
                    "user": rotated["user"],
                    "can_view_services": has_permission(rotated["user"], "view_services"),
                    "can_manage_admin": has_permission(rotated["user"], "manage_users"),
                }
            )
            set_auth_cookies(response, rotated["access_token"], rotated["refresh_token"])
            return response

        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "auth_mode": "login",
                "auth_error": None,
                "auth_message": None,
            }
        )

    return templates.TemplateResponse(
        "chat.html",
        {
            "request": request,
            "user": user,
            "can_view_services": has_permission(user, "view_services"),
            "can_manage_admin": has_permission(user, "manage_users"),
        }
    )
