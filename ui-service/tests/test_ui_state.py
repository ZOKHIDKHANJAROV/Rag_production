import asyncio
import importlib.util
import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[2]
UI_ROOT = ROOT / "ui-service"
UI_MAIN_PATH = ROOT / "ui-service" / "app" / "main.py"


def load_ui_module():
    module_name = f"ui_main_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, UI_MAIN_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec.loader is not None
    previous_cwd = Path.cwd()
    os.chdir(UI_ROOT)
    try:
        spec.loader.exec_module(module)
    finally:
        os.chdir(previous_cwd)
    return module


class StubRedis:
    def __init__(self):
        self.values = {}
        self.sets = {}

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, ex=None):
        self.values[key] = value
        return True

    async def delete(self, *keys):
        removed = 0
        for key in keys:
            if key in self.values:
                del self.values[key]
                removed += 1
            if key in self.sets:
                del self.sets[key]
                removed += 1
        return removed

    async def sadd(self, key, *values):
        bucket = self.sets.setdefault(key, set())
        before = len(bucket)
        bucket.update(values)
        return len(bucket) - before

    async def srem(self, key, *values):
        bucket = self.sets.setdefault(key, set())
        removed = 0
        for value in values:
            if value in bucket:
                bucket.remove(value)
                removed += 1
        return removed

    async def smembers(self, key):
        return set(self.sets.get(key, set()))

    async def scard(self, key):
        return len(self.sets.get(key, set()))

    async def expire(self, _key, _seconds):
        return True

    async def incr(self, key):
        current = int(self.values.get(key, "0"))
        current += 1
        self.values[key] = str(current)
        return current

    async def ping(self):
        return True

    async def aclose(self):
        return None


class StubDbPool:
    def __init__(self):
        self.users = {}
        self.audit_logs = []
        self.feedback = []

    def _user_row(self, username):
        user = self.users.get(username)
        if not user:
            return None
        return {
            "username": username,
            "password_hash": user["password_hash"],
            "role": user["role"],
            "created_at": user["created_at"],
            "updated_at": user["updated_at"],
        }

    async def execute(self, query, *args):
        compact = " ".join(query.split())
        now = datetime.now()

        if "CREATE TABLE IF NOT EXISTS ui_users" in compact:
            return "CREATE TABLE"

        if "INSERT INTO ui_users" in compact and "DO NOTHING" in compact:
            username, password_hash, role = args
            if username in self.users:
                return "INSERT 0 0"
            self.users[username] = {
                "password_hash": password_hash,
                "role": role,
                "created_at": now,
                "updated_at": now,
            }
            return "INSERT 0 1"

        if "INSERT INTO ui_users" in compact and "DO UPDATE" in compact:
            username, password_hash, role = args
            existing = self.users.get(username, {})
            self.users[username] = {
                "password_hash": password_hash,
                "role": role,
                "created_at": existing.get("created_at", now),
                "updated_at": now,
            }
            return "INSERT 0 1"

        if compact.startswith("DELETE FROM ui_users WHERE username = $1"):
            username = args[0]
            existed = username in self.users
            self.users.pop(username, None)
            return "DELETE 1" if existed else "DELETE 0"

        if "INSERT INTO admin_audit_logs" in compact:
            actor_username, action, target_type, target_id, details = args
            self.audit_logs.append(
                {
                    "id": len(self.audit_logs) + 1,
                    "actor_username": actor_username,
                    "action": action,
                    "target_type": target_type,
                    "target_id": target_id,
                    "details": json.loads(details),
                    "created_at": now,
                }
            )
            return "INSERT 0 1"

        if "INSERT INTO rag_feedback" in compact:
            username, session_id, answer_id, question, answer, sources, helpful = args
            existing = next(
                (
                    item for item in self.feedback
                    if item["username"] == username and item["answer_id"] == answer_id
                ),
                None,
            )
            if existing:
                existing["helpful"] = helpful
                existing["updated_at"] = now
            else:
                self.feedback.append(
                    {
                        "id": len(self.feedback) + 1,
                        "username": username,
                        "session_id": session_id,
                        "answer_id": answer_id,
                        "question": question,
                        "answer": answer,
                        "sources": json.loads(sources),
                        "helpful": helpful,
                        "created_at": now,
                        "updated_at": now,
                    }
                )
            return "INSERT 0 1"

        raise AssertionError(f"Unexpected execute query: {compact}")

    async def fetchrow(self, query, *args):
        compact = " ".join(query.split())
        now = datetime.now()

        if "FROM ui_users" in compact and "WHERE username = $1" in compact:
            return self._user_row(args[0])

        if compact.startswith("UPDATE ui_users SET"):
            username, password_hash, role = args
            existing = self.users.get(username)
            if not existing:
                return None
            self.users[username] = {
                "password_hash": password_hash or existing["password_hash"],
                "role": role or existing["role"],
                "created_at": existing["created_at"],
                "updated_at": now,
            }
            return self._user_row(username)

        raise AssertionError(f"Unexpected fetchrow query: {compact}")

    async def fetch(self, query, *args):
        compact = " ".join(query.split())

        if "FROM ui_users" in compact and "ORDER BY username" in compact:
            return [self._user_row(username) for username in sorted(self.users)]

        if "FROM admin_audit_logs" in compact:
            limit = args[0]
            return list(reversed(self.audit_logs))[:limit]

        raise AssertionError(f"Unexpected fetch query: {compact}")

    async def fetchval(self, query, *args):
        compact = " ".join(query.split())

        if compact == "SELECT 1":
            return 1

        if compact == "SELECT COUNT(*) FROM ui_users WHERE role = $1":
            role = args[0]
            return sum(1 for user in self.users.values() if user["role"] == role)

        raise AssertionError(f"Unexpected fetchval query: {compact}")

    async def aclose(self):
        return None


def prepare_ui_module(monkeypatch, tmp_path):
    monkeypatch.setenv("UI_USERS_FILE", str(tmp_path / "users.json"))
    monkeypatch.setenv("UI_USERS_JSON", "{}")
    ui_main = load_ui_module()
    ui_main.redis_client = StubRedis()
    ui_main.db_pool = StubDbPool()
    return ui_main


class StubHttpResponse:
    def __init__(self, status_code=200):
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f"Unexpected HTTP status: {self.status_code}")


class StubHttpClient:
    async def get(self, url, timeout=None):
        assert url.endswith("/health")
        assert timeout == 5
        return StubHttpResponse()


def test_bootstrap_admin_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("UI_USERS_FILE", str(tmp_path / "users.json"))
    monkeypatch.setenv("UI_USERS_JSON", "{}")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_USERNAME", "bootstrap")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "bootstrap-pass")

    ui_main = load_ui_module()
    ui_main.redis_client = StubRedis()
    ui_main.db_pool = StubDbPool()

    asyncio.run(ui_main.ensure_bootstrap_admin())
    stored_user = asyncio.run(ui_main.fetch_user_record("bootstrap"))

    assert stored_user["role"] == ui_main.ROLE_ADMIN
    assert stored_user["password"].startswith("pbkdf2_sha256$")


def test_refresh_tokens_are_stored_in_redis(monkeypatch, tmp_path):
    monkeypatch.delenv("BOOTSTRAP_ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("BOOTSTRAP_ADMIN_PASSWORD", raising=False)
    ui_main = prepare_ui_module(monkeypatch, tmp_path)

    asyncio.run(
        ui_main.create_user_record(
            "alice",
            ui_main.hash_password("pass123"),
            ui_main.ROLE_USER,
        )
    )
    user = asyncio.run(ui_main.fetch_user_record("alice"))
    issued = asyncio.run(ui_main.issue_auth_tokens("alice", user))
    token = issued["refresh_token"]
    payload = ui_main.decode_jwt(token, "refresh")
    stored = asyncio.run(ui_main.load_refresh_token_state(payload["jti"]))
    auth_session = asyncio.run(ui_main.load_auth_session_state(payload["sid"]))

    assert stored["username"] == "alice"
    assert auth_session["current_refresh_jti"] == payload["jti"]

    rotated = asyncio.run(ui_main.rotate_refresh_token(token))
    assert rotated["user"]["username"] == "alice"
    assert asyncio.run(ui_main.load_refresh_token_state(payload["jti"])) is None


def test_session_owner_is_enforced(monkeypatch, tmp_path):
    monkeypatch.delenv("BOOTSTRAP_ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("BOOTSTRAP_ADMIN_PASSWORD", raising=False)
    ui_main = prepare_ui_module(monkeypatch, tmp_path)

    for username in ("alice", "bob"):
        asyncio.run(
            ui_main.create_user_record(
                username,
                ui_main.hash_password(f"{username}-pass"),
                ui_main.ROLE_USER,
            )
        )

    alice = asyncio.run(ui_main.fetch_user_record("alice"))
    bob = asyncio.run(ui_main.fetch_user_record("bob"))
    alice_token = asyncio.run(ui_main.issue_auth_tokens("alice", alice))["access_token"]
    bob_token = asyncio.run(ui_main.issue_auth_tokens("bob", bob))["access_token"]

    with TestClient(ui_main.app) as client:
        client.cookies.set(ui_main.ACCESS_COOKIE_NAME, alice_token)
        created = client.post("/api/session/new")
        assert created.status_code == 200
        session_id = created.json()["session_id"]

        owner_view = client.get(f"/api/session/{session_id}")
        assert owner_view.status_code == 200

        client.cookies.set(ui_main.ACCESS_COOKIE_NAME, bob_token)
        forbidden = client.get(f"/api/session/{session_id}")
        assert forbidden.status_code == 403


def test_voice_tts_segments_wait_for_sentence_end(monkeypatch, tmp_path):
    ui_main = prepare_ui_module(monkeypatch, tmp_path)

    segments, remainder = ui_main.split_voice_tts_segments("First sentence. Incomplete")

    assert segments == ["First sentence."]
    assert remainder == "Incomplete"


def test_revoked_auth_session_blocks_access(monkeypatch, tmp_path):
    monkeypatch.delenv("BOOTSTRAP_ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("BOOTSTRAP_ADMIN_PASSWORD", raising=False)
    ui_main = prepare_ui_module(monkeypatch, tmp_path)

    asyncio.run(
        ui_main.create_user_record(
            "alice",
            ui_main.hash_password("alice-pass"),
            ui_main.ROLE_USER,
        )
    )
    user = asyncio.run(ui_main.fetch_user_record("alice"))
    issued = asyncio.run(ui_main.issue_auth_tokens("alice", user))
    access_token = issued["access_token"]
    auth_session_id = ui_main.decode_jwt(access_token, "access")["sid"]

    asyncio.run(ui_main.revoke_auth_session_state(auth_session_id, "alice"))

    with TestClient(ui_main.app) as client:
        client.cookies.set(ui_main.ACCESS_COOKIE_NAME, access_token)
        response = client.get("/api/me")
        assert response.status_code == 401


def test_stale_session_indexes_are_cleaned(monkeypatch, tmp_path):
    monkeypatch.delenv("BOOTSTRAP_ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("BOOTSTRAP_ADMIN_PASSWORD", raising=False)
    ui_main = prepare_ui_module(monkeypatch, tmp_path)

    asyncio.run(ui_main.redis_client.sadd(ui_main.session_index_key("alice"), "stale-session"))
    asyncio.run(ui_main.redis_client.sadd(ui_main.all_sessions_key(), "stale-session"))
    asyncio.run(ui_main.redis_client.sadd(ui_main.auth_session_index_key("alice"), "stale-auth"))

    assert asyncio.run(ui_main.count_live_sessions_for_user("alice")) == 0
    assert asyncio.run(ui_main.count_live_auth_sessions_for_user("alice")) == 0
    assert asyncio.run(ui_main.redis_client.smembers(ui_main.session_index_key("alice"))) == set()
    assert asyncio.run(ui_main.redis_client.smembers(ui_main.auth_session_index_key("alice"))) == set()
    assert asyncio.run(ui_main.redis_client.smembers(ui_main.all_sessions_key())) == set()


def test_health_checks_postgres_redis_and_rag(monkeypatch, tmp_path):
    monkeypatch.delenv("BOOTSTRAP_ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("BOOTSTRAP_ADMIN_PASSWORD", raising=False)
    ui_main = prepare_ui_module(monkeypatch, tmp_path)
    ui_main.http_client = StubHttpClient()

    payload = asyncio.run(ui_main.health())

    assert payload["status"] == "ok"
    assert payload["dependencies"] == {
        "redis": "ok",
        "postgres": "ok",
        "rag": "ok",
    }


def test_feedback_target_uses_the_answer_and_preceding_question(monkeypatch, tmp_path):
    ui_main = prepare_ui_module(monkeypatch, tmp_path)
    history = [
        {"type": "question", "content": "What is the deadline?"},
        {
            "type": "answer",
            "answer_id": "answer-1",
            "content": "Friday.",
            "sources": [{"filename": "policy.pdf"}],
        },
    ]

    target = ui_main.feedback_target_from_history(history, "answer-1")

    assert target == {
        "question": "What is the deadline?",
        "answer": "Friday.",
        "sources": [{"filename": "policy.pdf"}],
    }
    assert ui_main.feedback_target_from_history(history, "missing") is None


def test_feedback_api_persists_a_session_owned_answer(monkeypatch, tmp_path):
    ui_main = prepare_ui_module(monkeypatch, tmp_path)
    asyncio.run(
        ui_main.create_user_record(
            "alice",
            ui_main.hash_password("alice-pass"),
            ui_main.ROLE_USER,
        )
    )
    user = asyncio.run(ui_main.fetch_user_record("alice"))
    token = asyncio.run(ui_main.issue_auth_tokens("alice", user))["access_token"]
    session_id, session = asyncio.run(ui_main.create_session_state("alice"))
    session["history"] = [
        {"type": "question", "content": "What is the deadline?"},
        {
            "type": "answer",
            "answer_id": "answer-1",
            "content": "Friday.",
            "sources": [{"filename": "policy.pdf"}],
        },
    ]
    asyncio.run(ui_main.save_session_state(session_id, session))

    with TestClient(ui_main.app) as client:
        client.cookies.set(ui_main.ACCESS_COOKIE_NAME, token)
        response = client.post(
            "/api/feedback",
            json={
                "session_id": session_id,
                "answer_id": "answer-1",
                "helpful": False,
            },
        )

    assert response.status_code == 200
    assert ui_main.db_pool.feedback[0]["question"] == "What is the deadline?"
    assert ui_main.db_pool.feedback[0]["sources"] == [{"filename": "policy.pdf"}]
    saved_session = asyncio.run(ui_main.load_session_state(session_id))
    assert saved_session["history"][1]["feedback"] is False


def test_feedback_export_builds_evaluation_candidate(monkeypatch, tmp_path):
    ui_main = prepare_ui_module(monkeypatch, tmp_path)
    candidate = ui_main.feedback_to_evaluation_case(
        {
            "id": 7,
            "question": "What is the deadline?",
            "sources": [
                {"filename": "policy.pdf", "scope_key": "global"},
                {"filename": "policy.pdf", "scope_key": "global"},
                {"document_id": "private-doc", "scope_key": "user:alice"},
            ],
        }
    )

    assert candidate["id"] == "feedback-7"
    assert candidate["expected_sources"] == ["policy.pdf", "private-doc"]
    assert candidate["scope_keys"] == ["global", "user:alice"]
    assert candidate["expected_answer_contains"] == []
