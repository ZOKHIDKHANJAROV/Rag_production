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
EVALUATE_PATH = RAG_ROOT / "evaluation" / "evaluate.py"
EVALUATE_MODULE = None


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


def load_evaluate_module():
    global EVALUATE_MODULE
    if EVALUATE_MODULE is not None:
        return EVALUATE_MODULE

    module_name = f"rag_evaluate_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, EVALUATE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    EVALUATE_MODULE = module
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


def test_cache_key_changes_with_conversation_history():
    rag_main = load_rag_module()

    empty_history_key = rag_main.build_rag_cache_key(
        "What is the deadline?",
        ["global"],
        []
    )
    contextual_history_key = rag_main.build_rag_cache_key(
        "What is the deadline?",
        ["global"],
        [{"role": "user", "text": "Tell me about project Alpha."}]
    )

    assert empty_history_key != contextual_history_key


def test_fuse_search_results_rewards_agreement_between_queries():
    rag_main = load_rag_module()
    results = [
        {
            "document_id": "doc-a",
            "text": "Alpha deadline is Friday.",
            "score": 0.8,
            "query_rank": 1,
        },
        {
            "document_id": "doc-b",
            "text": "Beta deadline is Monday.",
            "score": 0.82,
            "query_rank": 1,
        },
        {
            "document_id": "doc-a",
            "text": "Alpha deadline is Friday.",
            "score": 0.78,
            "query_rank": 2,
        },
    ]

    fused = rag_main.fuse_search_results(results)
    by_document = {item["document_id"]: item for item in fused}

    assert len(fused) == 2
    assert by_document["doc-a"]["rrf_score"] > by_document["doc-b"]["rrf_score"]


def test_rerank_limits_chunks_from_the_same_document():
    rag_main = load_rag_module()
    original_limit = rag_main.RAG_MAX_CHUNKS_PER_DOCUMENT
    rag_main.RAG_MAX_CHUNKS_PER_DOCUMENT = 1
    docs = [
        {"document_id": "doc-a", "text": "First Alpha chunk"},
        {"document_id": "doc-a", "text": "Second Alpha chunk"},
        {"document_id": "doc-b", "text": "Beta chunk"},
    ]

    try:
        selected = rag_main.rerank_documents("question", docs)
    finally:
        rag_main.RAG_MAX_CHUNKS_PER_DOCUMENT = original_limit

    assert [item["document_id"] for item in selected] == ["doc-a", "doc-b"]


def test_trim_context_skips_an_oversized_chunk():
    rag_main = load_rag_module()
    original_limit = rag_main.MAX_CONTEXT_CHARS
    rag_main.MAX_CONTEXT_CHARS = 10

    try:
        contexts = rag_main.trim_context([
            "This chunk is too long",
            "short",
            "tiny",
        ])
    finally:
        rag_main.MAX_CONTEXT_CHARS = original_limit

    assert contexts == ["short", "tiny"]


def test_evaluation_reports_source_and_answer_match():
    evaluate = load_evaluate_module()
    case = {
        "id": "policy-deadline",
        "expected_sources": ["policy.pdf"],
        "expected_answer_contains": ["Friday"],
    }
    payload = {
        "answer": "The deadline is Friday.",
        "sources": [
            {"document_id": "doc-1", "filename": "policy.pdf"},
            {"document_id": "doc-2", "filename": "archive.pdf"},
        ],
    }

    result = evaluate.evaluate_response(case, payload, 42.0, 3)

    assert result["source_hit"] is True
    assert result["answer_match"] is True
    assert result["source_backed"] is True


def test_evaluation_report_calculates_metrics():
    evaluate = load_evaluate_module()
    report = evaluate.build_report([
        {
            "id": "one",
            "latency_ms": 10.0,
            "source_hit": True,
            "answer_match": True,
            "refusal_correct": None,
            "source_backed": True,
            "source_count": 1,
        },
        {
            "id": "two",
            "latency_ms": 30.0,
            "source_hit": False,
            "answer_match": False,
            "refusal_correct": True,
            "source_backed": False,
            "source_count": 0,
        },
    ], 0)

    assert report["source_hit_at_k"] == 0.5
    assert report["answer_keyword_match_rate"] == 0.5
    assert report["refusal_accuracy"] == 1.0
    assert report["source_backed_answer_rate"] == 0.5
    assert report["latency_ms"]["p95"] == 29.0
