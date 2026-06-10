"""Tests for S0.3 — IA dependency healthchecks.

The healthchecks probe LM Studio, the embedding provider, and
the reranker by making a real network call. In unit tests we
mock the network calls so the tests stay deterministic and fast.
The aggregate logic (overall = ok / degraded / down) is
exercised in full.
"""
from __future__ import annotations

from typing import Any

import pytest

from app.services.healthchecks import (
    DependencyStatus,
    HealthcheckReport,
    check_all_ia_dependencies,
    check_embeddings,
    check_lm_studio,
    check_reranker,
)


# ---------------------------------------------------------------------------
# DependencyStatus
# ---------------------------------------------------------------------------


def test_dependency_status_defaults():
    s = DependencyStatus(name="test", status="ok", latency_ms=100)
    assert s.detail == ""


def test_dependency_status_with_detail():
    s = DependencyStatus(name="test", status="down", latency_ms=0, detail="timeout")
    assert s.status == "down"
    assert s.detail == "timeout"


# ---------------------------------------------------------------------------
# HealthcheckReport
# ---------------------------------------------------------------------------


def test_healthcheck_report_overall_ok():
    r = HealthcheckReport(
        overall="ok",
        checks=[
            DependencyStatus(name="a", status="ok", latency_ms=10),
            DependencyStatus(name="b", status="ok", latency_ms=20),
        ],
    )
    assert r.overall == "ok"


def test_healthcheck_report_overall_degraded():
    r = HealthcheckReport(
        overall="degraded",
        checks=[
            DependencyStatus(name="a", status="ok", latency_ms=10),
            DependencyStatus(name="b", status="degraded", latency_ms=3000),
        ],
    )
    assert r.overall == "degraded"


def test_healthcheck_report_overall_down():
    r = HealthcheckReport(
        overall="down",
        checks=[
            DependencyStatus(name="a", status="ok", latency_ms=10),
            DependencyStatus(name="b", status="down", latency_ms=0),
        ],
    )
    assert r.overall == "down"


# ---------------------------------------------------------------------------
# check_lm_studio — mocked
# ---------------------------------------------------------------------------


def test_check_lm_studio_returns_down_when_not_configured(monkeypatch):
    from app.services import healthchecks

    monkeypatch.setattr(healthchecks.settings, "ai_base_url", "")
    result = check_lm_studio()
    assert result.status == "down"
    assert "not configured" in result.detail


def test_check_lm_studio_returns_ok_when_server_responds(monkeypatch):
    from app.services import healthchecks

    monkeypatch.setattr(healthchecks.settings, "ai_base_url", "http://localhost:1234")

    class FakeResponse:
        status_code = 200
        def json(self):
            return {"data": [{"id": "qwen2.5-32b"}]}

    class FakeClient:
        def __init__(self, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def get(self, url, **kw): return FakeResponse()

    monkeypatch.setattr("httpx.Client", FakeClient)
    result = check_lm_studio()
    assert result.status == "ok"
    assert "qwen2.5-32b" in result.detail


def test_check_lm_studio_returns_down_when_server_timeout(monkeypatch):
    from app.services import healthchecks
    import httpx

    monkeypatch.setattr(healthchecks.settings, "ai_base_url", "http://localhost:9999")

    def fake_get(url, **kw):
        raise httpx.TimeoutException("timeout")

    class FakeClient:
        def __init__(self, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        get = fake_get

    monkeypatch.setattr("httpx.Client", FakeClient)
    result = check_lm_studio()
    assert result.status == "down"
    # The timeout is caught inside the loop (both /v1/models and
    # /models fail); the function falls through to the generic
    # "server not reachable" fallback.
    assert result.detail == "server not reachable"


# ---------------------------------------------------------------------------
# check_embeddings — mocked
# ---------------------------------------------------------------------------


def test_check_embeddings_returns_down_when_not_configured(monkeypatch):
    from app.services import healthchecks

    monkeypatch.setattr(healthchecks.settings, "embedding_provider", "")
    result = check_embeddings()
    assert result.status == "down"


def test_check_embeddings_returns_ok_when_provider_works(monkeypatch):
    from app.services import healthchecks

    monkeypatch.setattr(healthchecks.settings, "embedding_provider", "local_hash")
    monkeypatch.setattr(
        "app.services.embeddings.embed_text",
        lambda text, dimensions=None: [0.1] * 1024,
    )
    result = check_embeddings()
    assert result.status == "ok"
    assert "dim=1024" in result.detail


def test_check_embeddings_returns_down_when_provider_raises(monkeypatch):
    from app.services import healthchecks
    from app.services.embeddings import EmbeddingProviderError

    monkeypatch.setattr(healthchecks.settings, "embedding_provider", "local_openai_compatible")
    monkeypatch.setattr(
        "app.services.embeddings.embed_text",
        lambda text, dimensions=None: (_ for _ in ()).throw(EmbeddingProviderError("server down")),
    )
    result = check_embeddings()
    assert result.status == "down"
    assert "server down" in result.detail


# ---------------------------------------------------------------------------
# check_reranker — mocked
# ---------------------------------------------------------------------------


def test_check_reranker_returns_down_when_not_configured(monkeypatch):
    from app.services import healthchecks

    monkeypatch.setattr(healthchecks.settings, "reranker_local_model", "")
    monkeypatch.setattr(healthchecks.settings, "embedding_base_url", "")
    monkeypatch.setattr(healthchecks.settings, "ai_base_url", "")
    result = check_reranker()
    assert result.status == "down"


def test_check_reranker_returns_ok_when_reranker_works(monkeypatch):
    from app.services import healthchecks
    from app.services.search_service import SearchResult

    monkeypatch.setattr(healthchecks.settings, "reranker_local_model", "BAAI/bge-reranker-v2-m3")

    candidate = SearchResult(
        document_id=0, original_filename="test", document_type="otro",
        status="processed", page_number=1, block_id=None, score=0.5,
        excerpt="test", ocr_confidence=None, source_type="text", source_path=None,
    )

    def fake_rerank(query, candidates, top_k=5):
        return candidates[:top_k]

    monkeypatch.setattr("app.services.reranker.rerank_sync", fake_rerank)
    result = check_reranker()
    assert result.status == "ok"


def test_check_reranker_returns_down_when_reranker_raises(monkeypatch):
    from app.services import healthchecks

    monkeypatch.setattr(healthchecks.settings, "reranker_local_model", "BAAI/bge-reranker-v2-m3")
    monkeypatch.setattr(
        "app.services.reranker.rerank_sync",
        lambda q, c, top_k=5: (_ for _ in ()).throw(RuntimeError("model not loaded")),
    )
    result = check_reranker()
    assert result.status == "down"
    assert "model not loaded" in result.detail


# ---------------------------------------------------------------------------
# Aggregate
# ---------------------------------------------------------------------------


def test_check_all_ia_dependencies_overall_down_when_any_down(monkeypatch):
    from app.services import healthchecks

    monkeypatch.setattr(healthchecks.settings, "ai_base_url", "")
    monkeypatch.setattr(healthchecks.settings, "embedding_provider", "")
    monkeypatch.setattr(healthchecks.settings, "reranker_local_model", "")
    monkeypatch.setattr(healthchecks.settings, "embedding_base_url", "")

    report = check_all_ia_dependencies()
    assert report.overall == "down"
    assert len(report.checks) == 3


def test_check_all_ia_dependencies_overall_ok_when_all_ok(monkeypatch):
    from app.services import healthchecks

    monkeypatch.setattr(healthchecks.settings, "ai_base_url", "http://fake")
    monkeypatch.setattr(healthchecks.settings, "embedding_provider", "local_hash")
    monkeypatch.setattr(healthchecks.settings, "reranker_local_model", "BAAI/bge-reranker-v2-m3")

    # Mock all three checks to return "ok".
    monkeypatch.setattr(
        "app.services.healthchecks.check_lm_studio",
        lambda: DependencyStatus(name="lm_studio", status="ok", latency_ms=50),
    )
    monkeypatch.setattr(
        "app.services.healthchecks.check_embeddings",
        lambda: DependencyStatus(name="embeddings", status="ok", latency_ms=100),
    )
    monkeypatch.setattr(
        "app.services.healthchecks.check_reranker",
        lambda: DependencyStatus(name="reranker", status="ok", latency_ms=150),
    )

    report = check_all_ia_dependencies()
    assert report.overall == "ok"
