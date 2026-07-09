import os
import importlib.util
import sys
import uuid
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[2]
LLM_ROOT = ROOT / "llm-service"
LLM_MAIN_PATH = LLM_ROOT / "app" / "main.py"


def load_llm_module():
    module_name = f"llm_main_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, LLM_MAIN_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec.loader is not None
    previous_cwd = Path.cwd()
    os.chdir(LLM_ROOT)
    try:
        spec.loader.exec_module(module)
    finally:
        os.chdir(previous_cwd)
    return module


class StubRedis:
    async def get(self, _key):
        return None

    async def setex(self, _key, _ttl, _value):
        return True

    async def aclose(self):
        return None


def test_internal_service_token_is_required(monkeypatch):
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "shared-secret")

    llm_main = load_llm_module()
    llm_main.redis_client = StubRedis()

    with TestClient(llm_main.app) as client:
        health = client.get("/health")
        assert health.status_code == 200

        unauthorized = client.post("/generate", json={"prompt": "hi"})
        assert unauthorized.status_code == 401

        authorized = client.post(
            "/generate",
            headers={"X-Service-Token": "shared-secret"},
            json={"prompt": "hi"},
        )
        assert authorized.status_code in {200, 500}
