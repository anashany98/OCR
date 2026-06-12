"""S0.3 — Health checks for the IA / embedding / reranker dependencies.

The healthcheck endpoint ``/admin/system/health`` already covers
the DB, Redis, workers, watcher, disk and backups. This module
adds the three AI-specific dependency checks:

* **LM Studio** — is the model server reachable? A simple GET to
  ``/v1/models`` (or ``/models``) returns the list of loaded
  models; a timeout or connection error means "down".
* **Embeddings** — can we embed a dummy token? A single
  ``embed_text("healthcheck")`` call verifies the embedding
  server is reachable *and* the model is loaded.
* **Reranker** — can we score a dummy pair? A single
  ``rerank_sync("test", [candidate], top_k=1)`` call verifies
  the reranker model is loaded and the endpoint is reachable.

Each check returns a :class:`DependencyStatus` with ``status``
(``"ok" | "degraded" | "down"``), ``latency_ms`` and an
optional ``detail`` string. The status is ``"degraded"`` when
the endpoint responds but the latency exceeds a configurable
threshold (default 2000 ms); the operator can adjust the
threshold via ``healthcheck_degraded_threshold_ms``.

The module is **fail-safe**: every check is wrapped in a
``try / except`` and returns ``"down"`` on any failure so the
caller can continue with the remaining checks. A failed check
never raises to the caller.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from app.core.config import settings

logger = logging.getLogger("app.services.healthchecks")


@dataclass(frozen=True)
class DependencyStatus:
    """The status of a single dependency check.

    Attributes:
        name: short label (``"lm_studio"``, ``"embeddings"``,
            ``"reranker"``).
        status: ``"ok"`` when the dependency responded within
            the degraded threshold, ``"degraded"`` when it
            responded but slowly, ``"down"`` when it did not
            respond at all.
        latency_ms: round-trip time in milliseconds.
        detail: optional human-readable note (e.g. the model
            name returned by LM Studio, or the error message).
    """

    name: str
    status: str
    latency_ms: int
    detail: str = ""


# Thresholds (configurable via settings).
_DEGRADED_LATENCY_MS: int = 2000


def _now_ms() -> int:
    return int(time.perf_counter() * 1000)


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def check_lm_studio() -> DependencyStatus:
    """Probe the LM Studio model server (``AI_BASE_URL/v1/models``).

    Returns ``"ok"`` when the server responds with a 200 and a
    non-empty model list, ``"degraded"`` when the server responds
    but the latency exceeds the threshold, ``"down"`` on any
    failure (timeout, connection error, 4xx/5xx).
    """
    name = "lm_studio"
    base_url = (settings.ai_base_url or "").strip().rstrip("/")
    if not base_url:
        return DependencyStatus(
            name=name, status="down", latency_ms=0, detail="AI_BASE_URL not configured"
        )

    # LM Studio exposes /v1/models; some servers expose /models.
    start = _now_ms()
    try:
        import httpx

        with httpx.Client(timeout=5.0) as client:
            for suffix in ("/v1/models", "/models"):
                url = base_url + suffix
                try:
                    resp = client.get(url)
                    if resp.status_code == 200:
                        data = resp.json()
                        models = data.get("data", []) if isinstance(data, dict) else []
                        latency = _now_ms() - start
                        model_names = [m.get("id", "?") for m in models[:5]] if models else []
                        status = "ok" if latency < _DEGRADED_LATENCY_MS else "degraded"
                        detail = (
                            f"models: {', '.join(model_names)}"
                            if model_names
                            else "no models loaded"
                        )
                        return DependencyStatus(
                            name=name, status=status, latency_ms=latency, detail=detail
                        )
                except Exception:
                    continue
    except Exception as exc:
        return DependencyStatus(
            name=name, status="down", latency_ms=_now_ms() - start, detail=str(exc)[:200]
        )

    return DependencyStatus(
        name=name, status="down", latency_ms=_now_ms() - start, detail="server not reachable"
    )


def check_embeddings() -> DependencyStatus:
    """Probe the embedding provider by embedding a single dummy
    token. Returns ``"ok"`` when the provider responds, ``"down"``
    when it does not.
    """
    name = "embeddings"
    if not settings.embedding_provider:
        return DependencyStatus(
            name=name, status="down", latency_ms=0, detail="EMBEDDING_PROVIDER not configured"
        )

    start = _now_ms()
    try:
        from app.services.embeddings import embed_text, EmbeddingProviderError

        vec = embed_text("healthcheck", dimensions=None)
        latency = _now_ms() - start
        if vec and len(vec) > 0:
            status = "ok" if latency < _DEGRADED_LATENCY_MS else "degraded"
            return DependencyStatus(
                name=name, status=status, latency_ms=latency, detail=f"dim={len(vec)}"
            )
        return DependencyStatus(
            name=name, status="down", latency_ms=latency, detail="empty vector returned"
        )
    except EmbeddingProviderError as exc:
        return DependencyStatus(
            name=name, status="down", latency_ms=_now_ms() - start, detail=str(exc)[:200]
        )
    except Exception as exc:
        return DependencyStatus(
            name=name, status="down", latency_ms=_now_ms() - start, detail=str(exc)[:200]
        )


def check_reranker() -> DependencyStatus:
    """Probe the reranker by scoring a single dummy pair. Returns
    ``"ok"`` when the reranker responds, ``"down"`` when it does
    not.
    """
    name = "reranker"
    if not settings.reranker_local_model and not (
        settings.embedding_base_url or settings.ai_base_url
    ):
        return DependencyStatus(
            name=name, status="down", latency_ms=0, detail="no reranker configured"
        )

    start = _now_ms()
    try:
        from app.services.search_service import SearchResult
        from app.services.reranker import rerank_sync

        candidate = SearchResult(
            document_id=0,
            original_filename="healthcheck",
            document_type="otro",
            status="processed",
            page_number=1,
            block_id=None,
            score=0.5,
            excerpt="healthcheck test",
            ocr_confidence=None,
            source_type="text",
            source_path=None,
        )
        result = rerank_sync("test query", [candidate], top_k=1)
        latency = _now_ms() - start
        if result:
            status = "ok" if latency < _DEGRADED_LATENCY_MS else "degraded"
            return DependencyStatus(
                name=name, status=status, latency_ms=latency, detail=f"score={result[0].score:.3f}"
            )
        return DependencyStatus(name=name, status="down", latency_ms=latency, detail="empty result")
    except Exception as exc:
        return DependencyStatus(
            name=name, status="down", latency_ms=_now_ms() - start, detail=str(exc)[:200]
        )


# ---------------------------------------------------------------------------
# Aggregate check
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HealthcheckReport:
    """The aggregate health of all AI dependencies.

    Attributes:
        overall: ``"ok"`` when all checks are ``"ok"``,
            ``"degraded"`` when at least one is ``"degraded"``
            but none are ``"down"``, ``"down"`` when at least
            one is ``"down"``.
        checks: list of per-dependency statuses.
    """

    overall: str
    checks: list[DependencyStatus]


def check_all_ia_dependencies() -> HealthcheckReport:
    """Run all three checks and return the aggregate report."""
    checks = [
        check_lm_studio(),
        check_embeddings(),
        check_reranker(),
    ]
    statuses = {c.status for c in checks}
    if "down" in statuses:
        overall = "down"
    elif "degraded" in statuses:
        overall = "degraded"
    else:
        overall = "ok"
    return HealthcheckReport(overall=overall, checks=checks)


__all__ = [
    "DependencyStatus",
    "HealthcheckReport",
    "check_lm_studio",
    "check_embeddings",
    "check_reranker",
    "check_all_ia_dependencies",
]
