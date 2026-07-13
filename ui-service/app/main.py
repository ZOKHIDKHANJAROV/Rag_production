from fastapi import FastAPI, Request, Response, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import httpx
import asyncpg
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
import redis.asyncio as redis
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

# =========================
# LOGGING
# =========================

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger("ui-service")
CORS_ALLOW_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ALLOW_ORIGINS",
        "http://localhost:8000,http://127.0.0.1:8000",
    ).split(",")
    if origin.strip()
]

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
    allow_origins=CORS_ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

templates = Jinja2Templates(directory="templates")

app.mount("/static", StaticFiles(directory="static"), name="static")

# =========================
# CONFIG
# =========================

RAG_URL = os.getenv(
    "RAG_SERVICE_URL",
    "http://rag-service:8003/ask"
)
RAG_STREAM_URL = RAG_URL.replace("/ask", "/ask/stream")

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
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.getenv("POSTGRES_DB", "rag_ui")
POSTGRES_USER = os.getenv("POSTGRES_USER", "rag_ui")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")
POSTGRES_DSN = os.getenv("POSTGRES_DSN", "")

SECRET_KEY = os.getenv("SECRET_KEY", "change-me")
INTERNAL_SERVICE_TOKEN = os.getenv("INTERNAL_SERVICE_TOKEN", "")
SERVICE_AUTH_HEADER = "X-Service-Token"
JWT_ALGORITHM = "HS256"
ACCESS_COOKIE_NAME = os.getenv("ACCESS_COOKIE_NAME", "rag_access")
REFRESH_COOKIE_NAME = os.getenv("REFRESH_COOKIE_NAME", "rag_refresh")
ACCESS_TOKEN_EXPIRE_SECONDS = int(os.getenv("ACCESS_TOKEN_EXPIRE_SECONDS", "900"))
REFRESH_TOKEN_EXPIRE_SECONDS = int(os.getenv("REFRESH_TOKEN_EXPIRE_SECONDS", "604800"))
AUTH_COOKIE_SECURE = os.getenv("AUTH_COOKIE_SECURE", "false").lower() == "true"
LEGACY_AUTH_COOKIE_NAME = "rag_auth"
USERS_FILE = Path(os.getenv("UI_USERS_FILE", "data/users.json"))
UI_USERS_JSON = os.getenv("UI_USERS_JSON", "")
BOOTSTRAP_ADMIN_USERNAME = os.getenv("BOOTSTRAP_ADMIN_USERNAME", "").strip()
BOOTSTRAP_ADMIN_PASSWORD = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "")
UI_STATE_PREFIX = os.getenv("UI_STATE_PREFIX", "ui")
UI_SESSION_TTL_SECONDS = int(
    os.getenv("UI_SESSION_TTL_SECONDS", str(REFRESH_TOKEN_EXPIRE_SECONDS))
)
LOGIN_RATE_LIMIT_ATTEMPTS = int(os.getenv("LOGIN_RATE_LIMIT_ATTEMPTS", "5"))
LOGIN_RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("LOGIN_RATE_LIMIT_WINDOW_SECONDS", "300"))
ASK_RATE_LIMIT_REQUESTS = int(os.getenv("ASK_RATE_LIMIT_REQUESTS", "60"))
ASK_RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("ASK_RATE_LIMIT_WINDOW_SECONDS", "60"))
UPLOAD_RATE_LIMIT_REQUESTS = int(os.getenv("UPLOAD_RATE_LIMIT_REQUESTS", "20"))
UPLOAD_RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("UPLOAD_RATE_LIMIT_WINDOW_SECONDS", "300"))

# Backward-compatible alias for code that expects the old auth cookie name.
AUTH_COOKIE_NAME = ACCESS_COOKIE_NAME
ROLE_ADMIN = "admin"
ROLE_USER = "user"
KNOWN_ROLES = {ROLE_ADMIN, ROLE_USER}

ROLE_LABELS = {
    ROLE_ADMIN: "РђРґРјРёРЅ",
    ROLE_USER: "РџРѕР»СЊР·РѕРІР°С‚РµР»СЊ",
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


class FeedbackRequest(BaseModel):
    session_id: str
    answer_id: str
    helpful: bool


class FeedbackSelectionRequest(BaseModel):
    selected_for_evaluation: bool


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


def load_legacy_seed_users():
    users = {}

    if UI_USERS_JSON:
        try:
            users = normalize_users(json.loads(UI_USERS_JSON))
        except json.JSONDecodeError:
            logger.warning("Invalid UI_USERS_JSON, falling back to default users")

    if USERS_FILE.exists():
        try:
            file_users = normalize_users(json.loads(USERS_FILE.read_text(encoding="utf-8")))
            users = {**users, **file_users}
        except (OSError, json.JSONDecodeError):
            logger.warning("Invalid UI users file '%s', ignoring it", USERS_FILE)

    return users


LEGACY_SEED_USERS = load_legacy_seed_users()


# Service URLs for health checks
SERVICES = {
    "rag": RAG_URL.replace("/ask", ""),
    "embedding": f"{EMBED_URL}",
    "ingestion": INGEST_URL.replace("/upload", ""),
    "llm": os.getenv("LLM_SERVICE_URL", "http://llm-service:8002"),
    "qdrant": os.getenv("QDRANT_URL", "http://qdrant:6333")
}

http_client: httpx.AsyncClient | None = None
redis_client: redis.Redis | None = None
db_pool: asyncpg.Pool | None = None


def create_redis_client() -> redis.Redis:
    return redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        decode_responses=True,
    )


def create_postgres_pool():
    if POSTGRES_DSN:
        return asyncpg.create_pool(POSTGRES_DSN, min_size=1, max_size=10)
    return asyncpg.create_pool(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        database=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        min_size=1,
        max_size=10,
    )


def ensure_db_ready() -> asyncpg.Pool:
    if db_pool is None:
        raise RuntimeError("Postgres pool is not initialized")
    return db_pool


async def init_postgres_schema():
    await ensure_db_ready().execute(
        """
        CREATE TABLE IF NOT EXISTS ui_users (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS admin_audit_logs (
            id BIGSERIAL PRIMARY KEY,
            actor_username TEXT NOT NULL,
            action TEXT NOT NULL,
            target_type TEXT NOT NULL,
            target_id TEXT,
            details JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE INDEX IF NOT EXISTS admin_audit_logs_created_at_idx
        ON admin_audit_logs (created_at DESC);

        CREATE TABLE IF NOT EXISTS rag_feedback (
            id BIGSERIAL PRIMARY KEY,
            username TEXT NOT NULL,
            session_id TEXT NOT NULL,
            answer_id TEXT NOT NULL,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            sources JSONB NOT NULL DEFAULT '[]'::jsonb,
            helpful BOOLEAN NOT NULL,
            selected_for_evaluation BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (username, answer_id)
        );

        CREATE INDEX IF NOT EXISTS rag_feedback_created_at_idx
        ON rag_feedback (created_at DESC);

        CREATE INDEX IF NOT EXISTS rag_feedback_helpful_idx
        ON rag_feedback (helpful, created_at DESC);

        ALTER TABLE rag_feedback
        ADD COLUMN IF NOT EXISTS selected_for_evaluation BOOLEAN NOT NULL DEFAULT FALSE;

        CREATE INDEX IF NOT EXISTS rag_feedback_selection_idx
        ON rag_feedback (selected_for_evaluation, created_at DESC);
        """
    )


def record_to_user(row: asyncpg.Record | None):
    if row is None:
        return None
    return {
        "username": row["username"],
        "password": row["password_hash"],
        "role": normalize_role(row["role"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


async def fetch_user_record(username: str):
    row = await ensure_db_ready().fetchrow(
        """
        SELECT username, password_hash, role, created_at, updated_at
        FROM ui_users
        WHERE username = $1
        """,
        username,
    )
    return record_to_user(row)


async def list_user_records():
    rows = await ensure_db_ready().fetch(
        """
        SELECT username, password_hash, role, created_at, updated_at
        FROM ui_users
        ORDER BY username
        """
    )
    return [record_to_user(row) for row in rows]


async def count_users_by_role(role: str):
    return await ensure_db_ready().fetchval(
        "SELECT COUNT(*) FROM ui_users WHERE role = $1",
        normalize_role(role),
    )


async def create_user_record(username: str, password_hash: str, role: str):
    result = await ensure_db_ready().execute(
        """
        INSERT INTO ui_users (username, password_hash, role)
        VALUES ($1, $2, $3)
        ON CONFLICT (username) DO NOTHING
        """,
        username,
        password_hash,
        normalize_role(role),
    )
    return result.endswith("1")


async def upsert_user_record(username: str, password_hash: str, role: str):
    await ensure_db_ready().execute(
        """
        INSERT INTO ui_users (username, password_hash, role)
        VALUES ($1, $2, $3)
        ON CONFLICT (username)
        DO UPDATE SET
            password_hash = EXCLUDED.password_hash,
            role = EXCLUDED.role,
            updated_at = NOW()
        """,
        username,
        password_hash,
        normalize_role(role),
    )
    return await fetch_user_record(username)


async def update_user_record(username: str, password_hash: str | None = None, role: str | None = None):
    row = await ensure_db_ready().fetchrow(
        """
        UPDATE ui_users
        SET
            password_hash = COALESCE($2, password_hash),
            role = COALESCE($3, role),
            updated_at = NOW()
        WHERE username = $1
        RETURNING username, password_hash, role, created_at, updated_at
        """,
        username,
        password_hash,
        normalize_role(role) if role is not None else None,
    )
    return record_to_user(row)


async def delete_user_record(username: str):
    result = await ensure_db_ready().execute(
        "DELETE FROM ui_users WHERE username = $1",
        username,
    )
    return result.endswith("1")


async def write_admin_audit_log(actor_username: str, action: str, target_type: str, target_id: str | None, details: Dict | None = None):
    await ensure_db_ready().execute(
        """
        INSERT INTO admin_audit_logs (actor_username, action, target_type, target_id, details)
        VALUES ($1, $2, $3, $4, $5::jsonb)
        """,
        actor_username,
        action,
        target_type,
        target_id,
        json.dumps(details or {}, ensure_ascii=False),
    )


async def list_admin_audit_logs(limit: int = 50):
    rows = await ensure_db_ready().fetch(
        """
        SELECT id, actor_username, action, target_type, target_id, details, created_at
        FROM admin_audit_logs
        ORDER BY created_at DESC
        LIMIT $1
        """,
        max(1, min(limit, 200)),
    )
    return [
        {
            "id": row["id"],
            "actor_username": row["actor_username"],
            "action": row["action"],
            "target_type": row["target_type"],
            "target_id": row["target_id"],
            "details": dict(row["details"] or {}),
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        }
        for row in rows
    ]


async def save_rag_feedback(
    username: str,
    session_id: str,
    answer_id: str,
    question: str,
    answer: str,
    sources: List[Dict],
    helpful: bool,
):
    await ensure_db_ready().execute(
        """
        INSERT INTO rag_feedback (
            username, session_id, answer_id, question, answer, sources, helpful
        )
        VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7)
        ON CONFLICT (username, answer_id)
        DO UPDATE SET
            helpful = EXCLUDED.helpful,
            updated_at = NOW()
        """,
        username,
        session_id,
        answer_id,
        question,
        answer,
        json.dumps(sources, ensure_ascii=False),
        helpful,
    )


async def list_rag_feedback(
    limit: int = 100,
    helpful: bool | None = None,
    selected_for_evaluation: bool | None = None,
):
    rows = await ensure_db_ready().fetch(
        """
        SELECT id, username, session_id, answer_id, question, answer, sources,
               helpful, selected_for_evaluation, created_at, updated_at
        FROM rag_feedback
        WHERE ($1::boolean IS NULL OR helpful = $1)
          AND ($2::boolean IS NULL OR selected_for_evaluation = $2)
        ORDER BY created_at DESC
        LIMIT $3
        """,
        helpful,
        selected_for_evaluation,
        max(1, min(limit, 500)),
    )

    return [
        {
            "id": row["id"],
            "username": row["username"],
            "session_id": row["session_id"],
            "answer_id": row["answer_id"],
            "question": row["question"],
            "answer": row["answer"],
            "sources": list(row["sources"] or []),
            "helpful": row["helpful"],
            "selected_for_evaluation": row["selected_for_evaluation"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        }
        for row in rows
    ]


async def set_rag_feedback_selection(feedback_id: int, selected_for_evaluation: bool):
    row = await ensure_db_ready().fetchrow(
        """
        UPDATE rag_feedback
        SET selected_for_evaluation = $2, updated_at = NOW()
        WHERE id = $1
        RETURNING id
        """,
        feedback_id,
        selected_for_evaluation,
    )
    return row is not None


def feedback_to_evaluation_case(feedback: Dict):
    sources = feedback.get("sources", [])
    expected_sources = []
    scope_keys = []

    for source in sources:
        source_id = source.get("filename") or source.get("document_id")
        if source_id and source_id not in expected_sources:
            expected_sources.append(source_id)

        scope_key = source.get("scope_key") or "global"
        if scope_key not in scope_keys:
            scope_keys.append(scope_key)

    return {
        "id": f"feedback-{feedback['id']}",
        "question": feedback["question"],
        "scope_keys": scope_keys or ["global"],
        "expected_sources": expected_sources,
        "expected_answer_contains": [],
        "expect_answerable": True,
        "review_note": "Verify expected sources and add expected_answer_contains before evaluation.",
    }


async def migrate_legacy_users():
    for username, data in LEGACY_SEED_USERS.items():
        existing = await fetch_user_record(username)
        if existing:
            continue
        password_hash = data["password"]
        if password_needs_rehash(password_hash):
            password_hash = hash_password(password_hash)
        created = await create_user_record(username, password_hash, data.get("role", ROLE_USER))
        if created:
            logger.warning("Migrated legacy UI user '%s' into Postgres", username)


@app.on_event("startup")
async def startup_event():
    global http_client, redis_client, db_pool
    http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(REQUEST_TIMEOUT, connect=5.0),
        limits=httpx.Limits(
            max_connections=UI_HTTP_MAX_CONNECTIONS,
            max_keepalive_connections=UI_HTTP_MAX_KEEPALIVE
        )
    )
    if redis_client is None:
        redis_client = create_redis_client()
    if db_pool is None:
        db_pool = await create_postgres_pool()
    await init_postgres_schema()
    await migrate_legacy_users()
    await ensure_bootstrap_admin()


@app.on_event("shutdown")
async def shutdown_event():
    if http_client:
        await http_client.aclose()
    if redis_client:
        await redis_client.aclose()
    if db_pool:
        await db_pool.aclose()

# =========================
# AUTH
# =========================

def service_headers() -> Dict[str, str]:
    return {SERVICE_AUTH_HEADER: INTERNAL_SERVICE_TOKEN} if INTERNAL_SERVICE_TOKEN else {}


def hash_password(password: str) -> str:
    salt = secrets.token_urlsafe(16)
    iterations = 260000
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    )
    return f"pbkdf2_sha256${iterations}${salt}${jwt_b64encode(digest)}"


def verify_password(plain_password: str, stored_password: str) -> bool:
    if stored_password.startswith("pbkdf2_sha256$"):
        try:
            _, iterations, salt, expected_hash = stored_password.split("$", 3)
            actual = hashlib.pbkdf2_hmac(
                "sha256",
                plain_password.encode("utf-8"),
                salt.encode("utf-8"),
                int(iterations),
            )
            return hmac.compare_digest(jwt_b64encode(actual), expected_hash)
        except (ValueError, TypeError):
            return False

    return hmac.compare_digest(plain_password, stored_password)


def password_needs_rehash(stored_password: str) -> bool:
    return not stored_password.startswith("pbkdf2_sha256$")


async def ensure_bootstrap_admin():
    if not BOOTSTRAP_ADMIN_USERNAME or not BOOTSTRAP_ADMIN_PASSWORD:
        return

    if await count_users_by_role(ROLE_ADMIN):
        return

    username = validate_registration_format(BOOTSTRAP_ADMIN_USERNAME, BOOTSTRAP_ADMIN_PASSWORD)
    await upsert_user_record(username, hash_password(BOOTSTRAP_ADMIN_PASSWORD), ROLE_ADMIN)
    logger.warning("Bootstrap admin '%s' was created from environment", username)


def ensure_redis_ready() -> redis.Redis:
    if redis_client is None:
        raise RuntimeError("Redis client is not initialized")
    return redis_client


def state_key(*parts: str) -> str:
    return ":".join([UI_STATE_PREFIX, *parts])


def session_storage_key(session_id: str) -> str:
    return state_key("session", session_id)


def session_index_key(username: str) -> str:
    return state_key("user-sessions", username)


def all_sessions_key() -> str:
    return state_key("sessions")


def refresh_token_storage_key(jti: str) -> str:
    return state_key("refresh-token", jti)


def refresh_token_index_key(username: str) -> str:
    return state_key("user-refresh-tokens", username)


def auth_session_storage_key(auth_session_id: str) -> str:
    return state_key("auth-session", auth_session_id)


def auth_session_index_key(username: str) -> str:
    return state_key("user-auth-sessions", username)


def user_documents_storage_key(username: str) -> str:
    return state_key("user-documents", username)


def global_documents_storage_key() -> str:
    return state_key("global-documents")


def rate_limit_storage_key(bucket: str, subject: str) -> str:
    return state_key("rate-limit", bucket, subject)


async def redis_get_json(key: str, default: Any = None):
    raw = await ensure_redis_ready().get(key)
    if raw is None:
        return default
    return json.loads(raw)


async def redis_set_json(key: str, value: Any, ttl_seconds: int | None = None):
    payload = json.dumps(value, ensure_ascii=False)
    if ttl_seconds:
        await ensure_redis_ready().set(key, payload, ex=ttl_seconds)
    else:
        await ensure_redis_ready().set(key, payload)


async def load_session_state(session_id: str):
    session = await redis_get_json(session_storage_key(session_id))
    if session:
        await ensure_redis_ready().expire(session_storage_key(session_id), UI_SESSION_TTL_SECONDS)
    return session


async def save_session_state(session_id: str, session: Dict):
    await redis_set_json(session_storage_key(session_id), session, ttl_seconds=UI_SESSION_TTL_SECONDS)
    store = ensure_redis_ready()
    await store.sadd(session_index_key(session["username"]), session_id)
    await store.sadd(all_sessions_key(), session_id)


async def create_session_state(username: str, session_id: str | None = None):
    new_session_id = session_id or str(uuid.uuid4())
    session = {
        "username": username,
        "history": [],
        "created": datetime.now().isoformat(),
        "documents": [],
    }
    await save_session_state(new_session_id, session)
    return new_session_id, session


async def delete_session_state(session_id: str):
    session = await load_session_state(session_id)
    if not session:
        return

    store = ensure_redis_ready()
    await store.delete(session_storage_key(session_id))
    await store.srem(session_index_key(session["username"]), session_id)
    await store.srem(all_sessions_key(), session_id)


async def load_visible_sessions(user: Dict):
    store = ensure_redis_ready()
    if is_admin(user):
        session_ids = sorted(await store.smembers(all_sessions_key()))
    else:
        session_ids = sorted(await store.smembers(session_index_key(user["username"])))

    visible_sessions = []
    for session_id in session_ids:
        session = await load_session_state(session_id)
        if not session:
            await store.srem(all_sessions_key(), session_id)
            if not is_admin(user):
                await store.srem(session_index_key(user["username"]), session_id)
            continue
        if is_admin(user) or session.get("username") == user["username"]:
            visible_sessions.append({"session_id": session_id, **session})
    return visible_sessions


async def count_live_sessions_for_user(username: str):
    store = ensure_redis_ready()
    live_sessions = 0

    for session_id in sorted(await store.smembers(session_index_key(username))):
        session = await load_session_state(session_id)
        if not session or session.get("username") != username:
            await store.srem(session_index_key(username), session_id)
            await store.srem(all_sessions_key(), session_id)
            continue
        live_sessions += 1

    return live_sessions


async def save_auth_session_state(auth_session_id: str, auth_session: Dict):
    ttl_seconds = max(1, auth_session["expires_at"] - int(time.time()))
    await redis_set_json(
        auth_session_storage_key(auth_session_id),
        auth_session,
        ttl_seconds=ttl_seconds,
    )
    store = ensure_redis_ready()
    await store.sadd(auth_session_index_key(auth_session["username"]), auth_session_id)
    await store.expire(auth_session_index_key(auth_session["username"]), REFRESH_TOKEN_EXPIRE_SECONDS)


async def load_auth_session_state(auth_session_id: str):
    return await redis_get_json(auth_session_storage_key(auth_session_id))


async def revoke_auth_session_state(auth_session_id: str, username: str | None = None):
    store = ensure_redis_ready()
    auth_session = await load_auth_session_state(auth_session_id)
    owner = username or (auth_session.get("username") if auth_session else None)
    if auth_session and auth_session.get("current_refresh_jti"):
        await revoke_refresh_token_state(auth_session["current_refresh_jti"], owner)
    await store.delete(auth_session_storage_key(auth_session_id))
    if owner:
        await store.srem(auth_session_index_key(owner), auth_session_id)


async def revoke_all_auth_sessions_for_user(username: str):
    store = ensure_redis_ready()
    auth_session_ids = await store.smembers(auth_session_index_key(username))
    for auth_session_id in auth_session_ids:
        await revoke_auth_session_state(auth_session_id, username)
    await store.delete(auth_session_index_key(username))


async def list_auth_sessions_for_user(username: str):
    store = ensure_redis_ready()
    auth_session_ids = sorted(await store.smembers(auth_session_index_key(username)))
    sessions = []
    for auth_session_id in auth_session_ids:
        auth_session = await load_auth_session_state(auth_session_id)
        if not auth_session:
            await store.srem(auth_session_index_key(username), auth_session_id)
            continue
        sessions.append({"auth_session_id": auth_session_id, **auth_session})
    return sessions


async def count_live_auth_sessions_for_user(username: str):
    return len(await list_auth_sessions_for_user(username))


async def store_refresh_token_state(jti: str, username: str, auth_session_id: str, expires_at: int):
    store = ensure_redis_ready()
    await redis_set_json(
        refresh_token_storage_key(jti),
        {
            "username": username,
            "auth_session_id": auth_session_id,
            "expires_at": expires_at,
        },
        ttl_seconds=max(1, expires_at - int(time.time())),
    )
    await store.sadd(refresh_token_index_key(username), jti)
    await store.expire(refresh_token_index_key(username), REFRESH_TOKEN_EXPIRE_SECONDS)


async def load_refresh_token_state(jti: str):
    return await redis_get_json(refresh_token_storage_key(jti))


async def revoke_refresh_token_state(jti: str, username: str | None = None):
    store = ensure_redis_ready()
    owner = username
    if owner is None:
        token_state = await load_refresh_token_state(jti)
        owner = token_state.get("username") if token_state else None

    await store.delete(refresh_token_storage_key(jti))
    if owner:
        await store.srem(refresh_token_index_key(owner), jti)


async def revoke_all_refresh_tokens_for_user(username: str):
    store = ensure_redis_ready()
    token_ids = await store.smembers(refresh_token_index_key(username))
    if token_ids:
        keys = [refresh_token_storage_key(token_id) for token_id in token_ids]
        await store.delete(*keys)
    await store.delete(refresh_token_index_key(username))


async def load_user_documents(username: str):
    return await redis_get_json(user_documents_storage_key(username), default=[])


async def append_user_document(username: str, document_entry: Dict):
    documents = await load_user_documents(username)
    documents.append(document_entry)
    await redis_set_json(user_documents_storage_key(username), documents)


async def delete_user_documents(username: str):
    await ensure_redis_ready().delete(user_documents_storage_key(username))


def normalize_document_entry(document: Dict):
    scope_key = (document.get("scope_key") or "global").strip() or "global"
    knowledge_base = document.get("knowledge_base") or ("global" if scope_key == "global" else "personal")
    owner_username = document.get("owner_username") or None
    return {
        **document,
        "scope_key": scope_key,
        "knowledge_base": knowledge_base,
        "owner_username": owner_username,
        "visibility": "global" if scope_key == "global" else "personal",
    }


def split_documents_by_visibility(documents: List[Dict]):
    normalized = [normalize_document_entry(document) for document in documents]
    global_documents = [document for document in normalized if document["scope_key"] == "global"]
    personal_documents = [document for document in normalized if document["scope_key"] != "global"]
    return normalized, global_documents, personal_documents


def feedback_target_from_history(history: List[Dict], answer_id: str):
    for index, item in enumerate(history):
        if item.get("type") != "answer" or item.get("answer_id") != answer_id:
            continue

        for previous in reversed(history[:index]):
            if previous.get("type") == "question":
                return {
                    "question": previous.get("content", ""),
                    "answer": item.get("content", ""),
                    "sources": item.get("sources", []),
                }
        return None
    return None


def client_identifier(request: Request):
    if request.client and request.client.host:
        return request.client.host
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return forwarded or "unknown"


async def enforce_rate_limit(bucket: str, subject: str, limit: int, window_seconds: int, detail: str):
    if limit <= 0 or window_seconds <= 0:
        return
    store = ensure_redis_ready()
    key = rate_limit_storage_key(bucket, subject)
    current = await store.incr(key)
    if current == 1:
        await store.expire(key, window_seconds)
    if current > limit:
        raise HTTPException(status_code=429, detail=detail)


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


def create_access_token(username: str, user: Dict, auth_session_id: str) -> str:
    now = int(time.time())
    session_user = serialize_user(username, user)
    return create_jwt({
        "sub": username,
        "sid": auth_session_id,
        "type": "access",
        "role": session_user["role"],
        "role_label": session_user["role_label"],
        "permissions": session_user["permissions"],
        "iat": now,
        "exp": now + ACCESS_TOKEN_EXPIRE_SECONDS,
        "jti": secrets.token_urlsafe(16),
    })


async def create_refresh_token(username: str, auth_session_id: str) -> str:
    now = int(time.time())
    jti = secrets.token_urlsafe(32)
    expires_at = now + REFRESH_TOKEN_EXPIRE_SECONDS
    await store_refresh_token_state(jti, username, auth_session_id, expires_at)
    existing_auth_session = await load_auth_session_state(auth_session_id) or {}
    await save_auth_session_state(
        auth_session_id,
        {
            "username": username,
            "created_at": existing_auth_session.get("created_at", now),
            "last_seen_at": now,
            "expires_at": expires_at,
            "current_refresh_jti": jti,
        },
    )
    return create_jwt({
        "sub": username,
        "sid": auth_session_id,
        "type": "refresh",
        "iat": now,
        "exp": expires_at,
        "jti": jti,
    })


async def issue_auth_tokens(username: str, user: Dict, auth_session_id: str | None = None):
    session_id = auth_session_id or secrets.token_urlsafe(24)
    access_token = create_access_token(username, user, session_id)
    refresh_token = await create_refresh_token(username, session_id)
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "auth_session_id": session_id,
    }


async def rotate_refresh_token(token: str) -> Dict:
    payload = decode_jwt(token, "refresh")
    jti = payload.get("jti")
    username = payload.get("sub")
    auth_session_id = payload.get("sid")
    stored_token = await load_refresh_token_state(jti)
    auth_session = await load_auth_session_state(auth_session_id)
    now = int(time.time())

    if not stored_token or stored_token.get("username") != username or stored_token.get("auth_session_id") != auth_session_id:
        raise HTTPException(status_code=401, detail="Refresh token revoked")

    if stored_token.get("expires_at", 0) < now:
        await revoke_refresh_token_state(jti, username)
        raise HTTPException(status_code=401, detail="Refresh token expired")

    if not auth_session or auth_session.get("username") != username or auth_session.get("current_refresh_jti") != jti:
        await revoke_refresh_token_state(jti, username)
        raise HTTPException(status_code=401, detail="Authentication session revoked")

    user = await fetch_user_record(username)
    if not user:
        await revoke_auth_session_state(auth_session_id, username)
        raise HTTPException(status_code=401, detail="Invalid token subject")

    await revoke_refresh_token_state(jti, username)
    tokens = await issue_auth_tokens(username, user, auth_session_id=auth_session_id)
    return {
        "user": serialize_user(username, user),
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "auth_session_id": auth_session_id,
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


async def user_from_access_payload(payload: Dict) -> Dict:
    username = payload.get("sub")
    auth_session_id = payload.get("sid")
    if not username or not auth_session_id:
        raise HTTPException(status_code=401, detail="Invalid token subject")

    auth_session = await load_auth_session_state(auth_session_id)
    if not auth_session or auth_session.get("username") != username:
        raise HTTPException(status_code=401, detail="Authentication session revoked")

    configured_record = await fetch_user_record(username)
    if not configured_record:
        await revoke_auth_session_state(auth_session_id, username)
        raise HTTPException(status_code=401, detail="Invalid token subject")

    configured_user = serialize_user(username, configured_record)
    token_role = normalize_role(payload.get("role", configured_user["role"]))

    if token_role != configured_user["role"]:
        await revoke_auth_session_state(auth_session_id, username)
        raise HTTPException(status_code=401, detail="User role changed")

    return configured_user


async def get_current_user(request: Request):
    token = request.cookies.get(ACCESS_COOKIE_NAME)

    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")

    return await user_from_access_payload(decode_jwt(token, "access"))


async def get_optional_user(request: Request):
    token = request.cookies.get(ACCESS_COOKIE_NAME)
    if not token:
        return None

    try:
        return await user_from_access_payload(decode_jwt(token, "access"))
    except HTTPException:
        return None


async def refresh_optional_user(request: Request):
    token = request.cookies.get(REFRESH_COOKIE_NAME)
    if not token:
        return None

    try:
        return await rotate_refresh_token(token)
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


async def require_session_owner(session_id: str, user: Dict):
    session = await load_session_state(session_id)

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


def validate_registration_format(username: str, password: str):
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

    return username


async def validate_registration(username: str, password: str):
    username = validate_registration_format(username, password)

    if await fetch_user_record(username):
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
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...)
):
    username = username.strip()
    await enforce_rate_limit(
        "login",
        f"{client_identifier(request)}:{username.lower()}",
        LOGIN_RATE_LIMIT_ATTEMPTS,
        LOGIN_RATE_LIMIT_WINDOW_SECONDS,
        "Too many login attempts",
    )
    user = await fetch_user_record(username)

    if not user or not verify_password(password, user["password"]):
        return render_login_page(
            request,
            mode="login",
            error="РќРµРІРµСЂРЅРѕРµ РёРјСЏ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ РёР»Рё РїР°СЂРѕР»СЊ",
            status_code=401
        )

    if password_needs_rehash(user["password"]):
        user = await update_user_record(username, password_hash=hash_password(password))

    tokens = await issue_auth_tokens(username, user)

    response = RedirectResponse(url="/", status_code=303)
    set_auth_cookies(response, tokens["access_token"], tokens["refresh_token"])
    return response


@app.post("/register")
async def register(
    request: Request,
    username: str = Form(...),
    password: str = Form(...)
):
    await enforce_rate_limit(
        "register",
        client_identifier(request),
        LOGIN_RATE_LIMIT_ATTEMPTS,
        LOGIN_RATE_LIMIT_WINDOW_SECONDS,
        "Too many registration attempts",
    )
    try:
        username = await validate_registration(username, password)
    except HTTPException as exc:
        return render_login_page(
            request,
            mode="register",
            error=str(exc.detail),
            status_code=exc.status_code
        )

    if not await create_user_record(username, hash_password(password), ROLE_USER):
        return render_login_page(
            request,
            mode="register",
            error="Username already exists",
            status_code=409
        )

    user = await fetch_user_record(username)
    if not user:
        return render_login_page(
            request,
            mode="register",
            error="Failed to create user",
            status_code=500
        )
    tokens = await issue_auth_tokens(username, user)

    response = RedirectResponse(url="/", status_code=303)
    set_auth_cookies(response, tokens["access_token"], tokens["refresh_token"])
    return response


@app.post("/refresh")
async def refresh(request: Request):
    token = request.cookies.get(REFRESH_COOKIE_NAME)

    if not token:
        raise HTTPException(status_code=401, detail="Refresh token required")

    rotated = await rotate_refresh_token(token)

    response = JSONResponse(content={
        "user": rotated["user"],
        "timestamp": datetime.now().isoformat()
    })
    set_auth_cookies(response, rotated["access_token"], rotated["refresh_token"])
    return response


@app.post("/logout")
async def logout(request: Request):
    refresh_token = request.cookies.get(REFRESH_COOKIE_NAME)
    access_token = request.cookies.get(ACCESS_COOKIE_NAME)

    if refresh_token:
        try:
            payload = decode_jwt(refresh_token, "refresh")
            await revoke_auth_session_state(payload.get("sid"), payload.get("sub"))
        except HTTPException:
            pass
    elif access_token:
        try:
            payload = decode_jwt(access_token, "access")
            await revoke_auth_session_state(payload.get("sid"), payload.get("sub"))
        except HTTPException:
            pass

    response = RedirectResponse(url="/", status_code=303)
    clear_auth_cookies(response)
    return response


@app.get("/api/me")
async def me(request: Request):
    user = await get_current_user(request)
    return user


@app.get("/api/auth/sessions")
async def auth_sessions(request: Request):
    user = await get_current_user(request)
    current_payload = decode_jwt(request.cookies.get(ACCESS_COOKIE_NAME), "access")
    current_auth_session_id = current_payload.get("sid")
    sessions = await list_auth_sessions_for_user(user["username"])

    return {
        "sessions": [
            {
                **session,
                "current": session["auth_session_id"] == current_auth_session_id,
            }
            for session in sessions
        ],
        "timestamp": datetime.now().isoformat()
    }


@app.post("/api/auth/sessions/revoke-all")
async def revoke_my_auth_sessions(request: Request):
    user = await get_current_user(request)
    await revoke_all_auth_sessions_for_user(user["username"])
    await revoke_all_refresh_tokens_for_user(user["username"])

    response = JSONResponse(
        content={
            "status": "revoked",
            "username": user["username"],
            "timestamp": datetime.now().isoformat(),
        }
    )
    clear_auth_cookies(response)
    return response

# =========================
# HEALTH CHECK
# =========================

@app.get("/health")
async def health():
    """Check overall system health"""
    try:
        if http_client is None:
            raise RuntimeError("HTTP client is not initialized")

        await ensure_redis_ready().ping()
        db_ready = await ensure_db_ready().fetchval("SELECT 1")
        if db_ready != 1:
            raise RuntimeError("Postgres health query failed")

        rag_health = await http_client.get(
            SERVICES["rag"] + "/health",
            timeout=5
        )
        rag_health.raise_for_status()

        return {
            "status": "ok",
            "service": "ui-service",
            "dependencies": {
                "redis": "ok",
                "postgres": "ok",
                "rag": "ok",
            },
            "timestamp": datetime.now().isoformat()
        }

    except (httpx.HTTPError, RuntimeError, asyncpg.PostgresError, redis.RedisError) as e:
        logger.error(f"Health check failed: {str(e)}")
        raise HTTPException(
            status_code=503,
            detail="Service unhealthy"
        )


@app.get("/api/services-status")
async def services_status(request: Request):
    """Get status of all backend services"""
    user = await get_current_user(request)
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
        user = await get_current_user(request)
        await enforce_rate_limit(
            "ask",
            user["username"],
            ASK_RATE_LIMIT_REQUESTS,
            ASK_RATE_LIMIT_WINDOW_SECONDS,
            "Too many questions",
        )

        if not question.strip():
            raise HTTPException(
                status_code=400,
                detail="Question cannot be empty"
            )

        # Create session if missing
        if not session_id:
            session_id = str(uuid.uuid4())

        # Initialize session if new
        session = await load_session_state(session_id)
        if session is None:
            _, session = await create_session_state(user["username"], session_id=session_id)
        else:
            session = await require_session_owner(session_id, user)

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
            headers=service_headers(),
            timeout=REQUEST_TIMEOUT
        )

        response.raise_for_status()
        result = response.json()
        answer_id = str(uuid.uuid4())

        # Store in session history
        session["history"].append({
            "type": "question",
            "content": question,
            "timestamp": datetime.now().isoformat()
        })
        
        session["history"].append({
            "type": "answer",
            "answer_id": answer_id,
            "content": result.get("answer"),
            "sources": result.get("sources", []),
            "timestamp": datetime.now().isoformat()
        })
        await save_session_state(session_id, session)

        logger.info(
            f"Answer generated | session={session_id}"
        )

        return JSONResponse(content={
            **result,
            "answer_id": answer_id,
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


@app.post("/ask/stream")
async def ask_stream(
    request: Request,
    question: str = Form(...),
    session_id: str = Form(None)
):
    """Ask a question and stream answer tokens from the RAG system."""
    try:
        user = await get_current_user(request)
        await enforce_rate_limit(
            "ask-stream",
            user["username"],
            ASK_RATE_LIMIT_REQUESTS,
            ASK_RATE_LIMIT_WINDOW_SECONDS,
            "Too many questions",
        )

        if not question.strip():
            raise HTTPException(
                status_code=400,
                detail="Question cannot be empty"
            )

        if not session_id:
            session_id = str(uuid.uuid4())

        session = await load_session_state(session_id)
        if session is None:
            _, session = await create_session_state(user["username"], session_id=session_id)
        else:
            session = await require_session_owner(session_id, user)

        payload = {
            "question": question,
            "session_id": rag_session_id(user["username"], session_id),
            "top_k": 5,
            "scope_keys": request_scope_keys(user)
        }

        async def stream():
            answer_parts = []
            sources = []
            answer_id = str(uuid.uuid4())

            yield json.dumps({
                "type": "session",
                "session_id": session_id,
                "timestamp": datetime.now().isoformat()
            }, ensure_ascii=False) + "\n"

            async with http_client.stream(
                "POST",
                RAG_STREAM_URL,
                json=payload,
                headers=service_headers(),
                timeout=REQUEST_TIMEOUT
            ) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    if not line:
                        continue

                    data = json.loads(line)

                    if data.get("type") == "delta":
                        answer_parts.append(data.get("text", ""))

                    if data.get("type") in {"sources", "done"}:
                        sources = data.get("sources", sources)

                    if data.get("type") == "done":
                        data["answer_id"] = answer_id

                    yield json.dumps(data, ensure_ascii=False) + "\n"

            answer = "".join(answer_parts)

            session["history"].append({
                "type": "question",
                "content": question,
                "timestamp": datetime.now().isoformat()
            })

            session["history"].append({
                "type": "answer",
                "answer_id": answer_id,
                "content": answer,
                "sources": sources,
                "timestamp": datetime.now().isoformat()
            })
            await save_session_state(session_id, session)

            logger.info(f"Streaming answer generated | session={session_id}")

        return StreamingResponse(stream(), media_type="application/x-ndjson")

    except httpx.HTTPError as e:
        logger.error(f"RAG stream service error: {str(e)}")
        raise HTTPException(
            status_code=502,
            detail="RAG service unavailable"
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.error(
            f"Streaming ask failed: {str(e)}",
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail="Internal server error"
        )


@app.post("/api/feedback")
async def submit_feedback(request: Request, feedback: FeedbackRequest):
    user = await get_current_user(request)
    session = await require_session_owner(feedback.session_id, user)
    target = feedback_target_from_history(session.get("history", []), feedback.answer_id)

    if target is None:
        raise HTTPException(status_code=404, detail="Answer not found in this session")

    await save_rag_feedback(
        user["username"],
        feedback.session_id,
        feedback.answer_id,
        target["question"],
        target["answer"],
        target["sources"],
        feedback.helpful,
    )

    for item in session.get("history", []):
        if item.get("type") == "answer" and item.get("answer_id") == feedback.answer_id:
            item["feedback"] = feedback.helpful
            break
    await save_session_state(feedback.session_id, session)

    return {
        "status": "saved",
        "answer_id": feedback.answer_id,
        "helpful": feedback.helpful,
        "timestamp": datetime.now().isoformat(),
    }

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
        user = await get_current_user(request)
        await enforce_rate_limit(
            "upload",
            user["username"],
            UPLOAD_RATE_LIMIT_REQUESTS,
            UPLOAD_RATE_LIMIT_WINDOW_SECONDS,
            "Too many uploads",
        )

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
            headers=service_headers(),
            timeout=REQUEST_TIMEOUT
        )

        response.raise_for_status()
        result = response.json()

        if result.get("error") or result.get("status") != "indexed":
            raise HTTPException(
                status_code=502,
                detail=result.get("error", "Ingestion service did not index the document")
            )

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

        if owner_username:
            await append_user_document(owner_username, document_entry)

        if session_id:
            session = await load_session_state(session_id)
            if session:
                session = await require_session_owner(session_id, user)
            else:
                _, session = await create_session_state(user["username"], session_id=session_id)
            session["documents"].append(document_entry)
            await save_session_state(session_id, session)

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
        user = await get_current_user(request)
        logger.debug("Fetching documents")

        params = {"all_scopes": "true"} if has_permission(user, "view_all_documents") else {"owner_username": user["username"]}

        resp = await http_client.get(
            f"{EMBED_URL}/documents",
            params=params,
            headers=service_headers(),
            timeout=REQUEST_TIMEOUT
        )

        resp.raise_for_status()
        docs = resp.json()
        documents_payload = docs if isinstance(docs, list) else docs.get("documents", [])
        documents_payload, global_documents, personal_documents = split_documents_by_visibility(documents_payload)

        return {
            "documents": documents_payload,
            "global_documents": global_documents,
            "personal_documents": personal_documents,
            "counts": {
                "all": len(documents_payload),
                "global": len(global_documents),
                "personal": len(personal_documents),
            },
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
async def get_session(request: Request, session_id: str):
    """Get session details including history"""
    user = await get_current_user(request)
    session = await require_session_owner(session_id, user)
    
    return {
        "session_id": session_id,
        **session,
        "timestamp": datetime.now().isoformat()
    }


@app.post("/api/session/new")
async def create_session(request: Request):
    """Create a new session"""
    user = await get_current_user(request)
    session_id, session = await create_session_state(user["username"])
    
    logger.info(f"New session created: {session_id} | user={user['username']}")
    
    return {
        "session_id": session_id,
        "created": session["created"],
        "timestamp": datetime.now().isoformat()
    }


@app.get("/api/session/{session_id}/history")
async def get_history(request: Request, session_id: str):
    """Get chat history for a session"""
    user = await get_current_user(request)
    session = await require_session_owner(session_id, user)
    
    return {
        "session_id": session_id,
        "history": session["history"],
        "timestamp": datetime.now().isoformat()
    }


@app.delete("/api/session/{session_id}")
async def delete_session(request: Request, session_id: str):
    """Delete a session"""
    user = await get_current_user(request)
    await require_session_owner(session_id, user)
    
    await delete_session_state(session_id)
    
    logger.info(f"Session deleted: {session_id}")
    
    return {
        "message": "Session deleted",
        "session_id": session_id,
        "timestamp": datetime.now().isoformat()
    }


@app.get("/api/sessions")
async def list_sessions(request: Request):
    """List all sessions"""
    user = await get_current_user(request)
    visible_sessions = await load_visible_sessions(user)

    return {
        "sessions": visible_sessions,
        "count": len(visible_sessions),
        "timestamp": datetime.now().isoformat()
    }


# =========================
# ADMIN
# =========================

@app.get("/api/admin/users")
async def admin_list_users(request: Request):
    user = await get_current_user(request)
    require_permission(user, "manage_users")

    user_rows = await list_user_records()
    documents_resp = await http_client.get(
        f"{EMBED_URL}/documents",
        params={"all_scopes": "true"},
        headers=service_headers(),
        timeout=REQUEST_TIMEOUT
    )
    documents_resp.raise_for_status()
    documents_payload = documents_resp.json()
    if not isinstance(documents_payload, list):
        documents_payload = documents_payload.get("documents", [])

    personal_document_counts = {}
    for document in documents_payload:
        normalized_document = normalize_document_entry(document)
        owner_username = normalized_document.get("owner_username")
        if normalized_document["scope_key"] != "global" and owner_username:
            personal_document_counts[owner_username] = personal_document_counts.get(owner_username, 0) + 1

    return {
        "users": [
            {
                **serialize_user(data["username"], data),
                "sessions": await count_live_sessions_for_user(data["username"]),
                "active_auth_sessions": await count_live_auth_sessions_for_user(data["username"]),
                "documents": personal_document_counts.get(data["username"], 0),
            }
            for data in user_rows
        ],
        "timestamp": datetime.now().isoformat()
    }


@app.post("/api/admin/users")
async def admin_create_user(request: Request, payload: AdminUserCreate):
    user = await get_current_user(request)
    require_permission(user, "manage_users")

    username = await validate_registration(payload.username, payload.password)
    created = await create_user_record(
        username,
        hash_password(payload.password),
        normalize_role(payload.role),
    )
    if not created:
        raise HTTPException(status_code=409, detail="Username already exists")
    created_user = await fetch_user_record(username)
    await write_admin_audit_log(
        user["username"],
        "create_user",
        "user",
        username,
        {"role": normalize_role(payload.role)},
    )

    return {
        "user": serialize_user(username, created_user),
        "timestamp": datetime.now().isoformat()
    }


@app.patch("/api/admin/users/{username}")
async def admin_update_user(request: Request, username: str, payload: AdminUserUpdate):
    user = await get_current_user(request)
    require_permission(user, "manage_users")

    existing_user = await fetch_user_record(username)
    if not existing_user:
        raise HTTPException(status_code=404, detail="User not found")

    password_hash = None
    if payload.password is not None:
        if len(payload.password) < 6:
            raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
        password_hash = hash_password(payload.password)

    normalized_role = normalize_role(payload.role) if payload.role is not None else None
    updated_user = await update_user_record(username, password_hash=password_hash, role=normalized_role)

    if not updated_user:
        raise HTTPException(status_code=404, detail="User not found")

    if password_hash is not None or normalized_role is not None:
        await revoke_all_auth_sessions_for_user(username)
        await revoke_all_refresh_tokens_for_user(username)

    await write_admin_audit_log(
        user["username"],
        "update_user",
        "user",
        username,
        {
            "password_reset": password_hash is not None,
            "role": updated_user["role"],
        },
    )

    return {
        "user": serialize_user(username, updated_user),
        "timestamp": datetime.now().isoformat()
    }


@app.delete("/api/admin/users/{username}")
async def admin_delete_user(request: Request, username: str):
    user = await get_current_user(request)
    require_permission(user, "manage_users")

    if username == user["username"]:
        raise HTTPException(status_code=400, detail="Admin cannot delete own account")

    existing_user = await fetch_user_record(username)
    if not existing_user:
        raise HTTPException(status_code=404, detail="User not found")

    await delete_user_record(username)

    for session_id in await ensure_redis_ready().smembers(session_index_key(username)):
        await delete_session_state(session_id)

    await delete_user_documents(username)
    await revoke_all_auth_sessions_for_user(username)
    await revoke_all_refresh_tokens_for_user(username)

    try:
        await http_client.post(
            f"{EMBED_URL}/scope/{user_scope_key(username)}/delete",
            headers=service_headers(),
            timeout=REQUEST_TIMEOUT
        )
    except httpx.HTTPError:
        logger.warning("Failed to delete vector scope for user '%s'", username)

    await write_admin_audit_log(
        user["username"],
        "delete_user",
        "user",
        username,
        {"role": existing_user["role"]},
    )

    return {
        "status": "deleted",
        "username": username,
        "timestamp": datetime.now().isoformat()
    }


@app.post("/api/admin/users/{username}/revoke-sessions")
async def admin_revoke_user_sessions(request: Request, username: str):
    user = await get_current_user(request)
    require_permission(user, "manage_users")

    target_user = await fetch_user_record(username)
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    await revoke_all_auth_sessions_for_user(username)
    await revoke_all_refresh_tokens_for_user(username)
    await write_admin_audit_log(
        user["username"],
        "revoke_sessions",
        "user",
        username,
        {},
    )

    return {
        "status": "revoked",
        "username": username,
        "timestamp": datetime.now().isoformat()
    }


@app.get("/api/admin/audit-logs")
async def admin_audit_logs(request: Request, limit: int = 50):
    user = await get_current_user(request)
    require_permission(user, "manage_users")

    return {
        "logs": await list_admin_audit_logs(limit=limit),
        "timestamp": datetime.now().isoformat()
    }


@app.get("/api/admin/feedback")
async def admin_feedback(
    request: Request,
    limit: int = 100,
    helpful: bool | None = None,
    selected_for_evaluation: bool | None = None,
):
    user = await get_current_user(request)
    require_permission(user, "manage_users")

    return {
        "feedback": await list_rag_feedback(
            limit=limit,
            helpful=helpful,
            selected_for_evaluation=selected_for_evaluation,
        ),
        "timestamp": datetime.now().isoformat(),
    }


@app.patch("/api/admin/feedback/{feedback_id}/evaluation")
async def admin_select_feedback_for_evaluation(
    request: Request,
    feedback_id: int,
    selection: FeedbackSelectionRequest,
):
    user = await get_current_user(request)
    require_permission(user, "manage_users")

    if not await set_rag_feedback_selection(
        feedback_id,
        selection.selected_for_evaluation,
    ):
        raise HTTPException(status_code=404, detail="Feedback not found")

    await write_admin_audit_log(
        user["username"],
        "select_feedback_for_evaluation",
        "feedback",
        str(feedback_id),
        {"selected_for_evaluation": selection.selected_for_evaluation},
    )
    return {
        "status": "updated",
        "id": feedback_id,
        "selected_for_evaluation": selection.selected_for_evaluation,
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/api/admin/feedback/evaluation-candidates")
async def admin_feedback_evaluation_candidates(request: Request, limit: int = 200):
    user = await get_current_user(request)
    require_permission(user, "manage_users")
    feedback = await list_rag_feedback(
        limit=limit,
        selected_for_evaluation=True,
    )

    return {
        "cases": [feedback_to_evaluation_case(item) for item in feedback],
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/api/admin/databases")
async def admin_databases(request: Request):
    user = await get_current_user(request)
    require_permission(user, "manage_documents")

    resp = await http_client.get(
        f"{EMBED_URL}/documents",
        params={"all_scopes": "true"},
        headers=service_headers(),
        timeout=REQUEST_TIMEOUT
    )
    resp.raise_for_status()
    documents = resp.json()
    if not isinstance(documents, list):
        documents = documents.get("documents", [])

    user_rows = await list_user_records()
    counts = {"global": 0}
    for user_row in user_rows:
        counts[user_scope_key(user_row["username"])] = 0

    for doc in documents:
        scope = normalize_document_entry(doc)["scope_key"]
        counts[scope] = counts.get(scope, 0) + 1

    return {
        "databases": [
            {
                "scope_key": "global",
                "name": "РћСЃРЅРѕРІРЅР°СЏ Р±Р°Р·Р°",
                "type": "global",
                "owner_username": None,
                "documents": counts.get("global", 0),
            },
            *[
                {
                    "scope_key": user_scope_key(username),
                    "name": f"Р›РёС‡РЅР°СЏ Р±Р°Р·Р°: {username}",
                    "type": "personal",
                    "owner_username": username,
                    "documents": counts.get(user_scope_key(username), 0),
                }
                for username in sorted(user_row["username"] for user_row in user_rows)
            ]
        ],
        "timestamp": datetime.now().isoformat()
    }


@app.get("/api/admin/documents")
async def admin_documents(request: Request, scope_key: str = None):
    user = await get_current_user(request)
    require_permission(user, "manage_documents")

    params = {"all_scopes": "true"} if not scope_key else {"scope_key": scope_key}
    resp = await http_client.get(
        f"{EMBED_URL}/documents",
        params=params,
        headers=service_headers(),
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
    user = await get_current_user(request)
    require_permission(user, "manage_documents")

    resp = await http_client.post(
        f"{EMBED_URL}/documents/{document_id}/delete",
        params={"scope_key": scope_key},
        headers=service_headers(),
        timeout=REQUEST_TIMEOUT
    )
    resp.raise_for_status()

    await write_admin_audit_log(
        user["username"],
        "delete_document",
        "document",
        document_id,
        {"scope_key": scope_key},
    )

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
async def chat_page(request: Request):
    """Render main chat interface"""
    logger.debug("Rendering chat UI")
    user = await get_optional_user(request)

    if not user:
        rotated = await refresh_optional_user(request)
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


