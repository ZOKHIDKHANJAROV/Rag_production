import asyncio
import importlib.util
import os
import sys
import uuid
from pathlib import Path

from fastapi import HTTPException


ROOT = Path(__file__).resolve().parents[2]
RAG_ROOT = ROOT / "rag-service"
RAG_MAIN_PATH = RAG_ROOT / "app" / "main.py"
RAG_MODULE = None


def load_rag_module():
    global RAG_MODULE
    if RAG_MODULE is not None:
        return RAG_MODULE

    module_name = f"rag_main_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, RAG_MAIN_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec.loader is not None
    previous_cwd = Path.cwd()
    os.chdir(RAG_ROOT)
    try:
        spec.loader.exec_module(module)
    finally:
        os.chdir(previous_cwd)
    RAG_MODULE = module
    return module


class StubRedis:
    async def ping(self):
        return True

    async def aclose(self):
        return None


class StubResponse:
    def __init__(self, status_code=200):
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"Unexpected HTTP status {self.status_code}")


class HealthyHttpClient:
    async def get(self, url, timeout=None):
        assert url.endswith("/health")
        assert timeout == 5.0
        return StubResponse()

    async def aclose(self):
        return None


class FailingHttpClient:
    async def get(self, url, timeout=None):
        raise RuntimeError(f"dependency unavailable: {url}")

    async def aclose(self):
        return None


def test_rag_health_reports_dependency_status():
    rag_main = load_rag_module()
    rag_main.redis_client = StubRedis()
    rag_main.client = HealthyHttpClient()

    payload = asyncio.run(rag_main.health())

    assert payload["status"] == "ok"
    assert payload["dependencies"] == {
        "redis": "ok",
        "llm": "ok",
        "vector": "ok",
    }


def test_rag_health_fails_when_dependency_is_unavailable():
    rag_main = load_rag_module()
    rag_main.redis_client = StubRedis()
    rag_main.client = FailingHttpClient()

    try:
        asyncio.run(rag_main.health())
    except HTTPException as exc:
        assert exc.status_code == 503
        assert exc.detail == "Service unhealthy"
    else:
        raise AssertionError("Expected health check failure")
