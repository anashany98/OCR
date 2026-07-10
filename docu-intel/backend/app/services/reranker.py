"""Cross-encoder reranker for improving hybrid search precision.

Two backends are supported:

1. **HTTP** (default, backward-compatible): the existing OpenAI-compatible
   ``/rerank`` endpoint. Useful when the reranker runs in a separate
   inference server (TEI, vLLM, LM Studio, etc.) or when the
   ``embedding_base_url`` points at a shared inference host.

2. **In-process** (``sentence_transformers.CrossEncoder``): the
   reranker model loads directly into the worker. Default model is
   ``BAAI/bge-reranker-v2-m3`` (multilingual, 568M params). The model
   is downloaded from HuggingFace on first use (~1.1 GB).

The backend is selected by setting ``reranker_local_model`` to a
non-empty string in the environment. Otherwise the HTTP path is used.

Both paths fall back to the original candidate order on any error, so a
broken reranker never blocks search.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass

import httpx

from app.core.config import settings
from app.services.search_service import SearchResult

logger = logging.getLogger("app.services.reranker")

RERANKER_ENDPOINT = "/rerank"
RERANKER_TIMEOUT = 8.0
MIN_CANDIDATES_FOR_RERANK = 5


@dataclass(frozen=True)
class RerankerResult:
    index: int
    score: float


# ---------------------------------------------------------------------------
# In-process reranker (sentence-transformers CrossEncoder)
# ---------------------------------------------------------------------------


@dataclass
class LocalSentenceTransformerReranker:
    """Lazy-loaded BGE-reranker-v2-m3 (or compatible) cross-encoder.

    Scores ``(query, passage)`` pairs in a single forward pass. Output
    is a single float per pair; we sort descending and return the top
    ``top_k`` indices in their original SearchResult order.
    """

    model_name: str
    device: str = "cuda"
    max_length: int = 512

    _model: object = None  # CrossEncoder | None
    _init_lock: threading.Lock = None  # type: ignore[assignment]
    _init_error: BaseException | None = None

    def __post_init__(self) -> None:
        self._init_lock = threading.Lock()

    def _ensure_loaded(self) -> object:
        if self._model is not None:
            return self._model
        with self._init_lock:
            if self._model is not None:
                return self._model
            if self._init_error is not None:
                raise self._init_error
            try:
                from sentence_transformers import CrossEncoder  # type: ignore[import-not-found]

                self._model = CrossEncoder(
                    self.model_name,
                    device=self.device,
                    max_length=self.max_length,
                )
            except Exception as exc:
                self._init_error = exc
                raise
        return self._model

    def score(self, query: str, passages: list[str]) -> list[float]:
        """Return one relevance score per passage. Higher = more relevant."""
        if not passages:
            return []
        model = self._ensure_loaded()
        pairs = [(query, p) for p in passages]
        raw = model.predict(pairs, show_progress_bar=False, convert_to_numpy=True)
        return [float(s) for s in raw]


_local_reranker: LocalSentenceTransformerReranker | None = None
_local_reranker_lock = threading.Lock()


def get_local_reranker() -> LocalSentenceTransformerReranker:
    """Worker-scoped singleton local reranker, built from settings."""
    global _local_reranker
    if _local_reranker is not None:
        return _local_reranker
    with _local_reranker_lock:
        if _local_reranker is not None:
            return _local_reranker
        device = settings.reranker_local_device
        # Auto-detect CUDA: if configured for cuda but unavailable, fall back to cpu
        if device == "cuda":
            try:
                import torch
                if not torch.cuda.is_available():
                    device = "cpu"
                    logger.info("CUDA not available for reranker, using CPU")
            except ImportError:
                device = "cpu"
                logger.info("torch not installed, reranker using CPU")
        _local_reranker = LocalSentenceTransformerReranker(
            model_name=settings.reranker_local_model,
            device=device,
            max_length=settings.reranker_local_max_length,
        )
    return _local_reranker


def _reranker_url() -> str | None:
    """Resolve the reranker endpoint URL from settings."""
    base = settings.embedding_base_url.strip() or settings.ai_base_url.strip()
    if not base:
        return None
    clean = base.rstrip("/")
    return f"{clean}{RERANKER_ENDPOINT}"


async def rerank(
    query: str,
    candidates: list[SearchResult],
    top_k: int = 5,
) -> list[SearchResult]:
    """Reorder candidates using a cross-encoder reranker.

    Two backends are tried in order:

    1. **In-process** if ``settings.reranker_local_model`` is non-empty.
       Loads BGE-reranker-v2-m3 (or whatever's configured) into the
       worker the first time, then reuses it.
    2. **HTTP** if ``settings.embedding_base_url`` (or
       ``settings.ai_base_url``) points at an OpenAI-compatible
       ``/rerank`` endpoint. Used when the reranker lives in a
       separate inference server.

    Both paths fall back to the original candidate order on any error,
    so a broken reranker never blocks search.

    Args:
        query: The search query text.
        candidates: Candidate search results to rerank.
        top_k: Number of top results to return after reranking.

    Returns:
        Reranked list of at most top_k SearchResult items.
    """
    if len(candidates) <= MIN_CANDIDATES_FOR_RERANK:
        return candidates[:top_k]

    # Path 1: in-process. Fastest, no network hop, no extra service.
    if settings.reranker_local_model.strip():
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(None, _rerank_local_sync, query, candidates, top_k)
        except Exception as exc:
            logger.warning("Local reranker failed, falling back: %s", exc)
            return candidates[:top_k]

    # Path 2: HTTP /rerank endpoint. Backward-compatible default.
    url = _reranker_url()
    if url is None:
        return candidates[:top_k]

    documents = [getattr(c, "full_text", None) or c.excerpt for c in candidates]

    try:
        async with httpx.AsyncClient(timeout=RERANKER_TIMEOUT) as client:
            response = await client.post(
                url,
                json={"query": query, "documents": documents},
            )

        if response.status_code != 200:
            logger.debug("Reranker returned status %d, using original order", response.status_code)
            return candidates[:top_k]

        data = response.json()
        results = data.get("results", [])

        if not results:
            return candidates[:top_k]

        # Build reranked list preserving original SearchResult objects
        reranked: list[SearchResult] = []
        seen: set[int] = set()
        for item in results:
            if isinstance(item, dict):
                idx = item.get("index", -1)
                score = item.get("relevance_score", item.get("score", 0.0))
            elif isinstance(item, (int, float)):
                idx = int(item)
                score = 0.0
            else:
                continue

            if 0 <= idx < len(candidates) and idx not in seen:
                seen.add(idx)
                # Update score with reranker confidence
                original = candidates[idx]
                reranked.append(
                    original.__class__(
                        document_id=original.document_id,
                        original_filename=original.original_filename,
                        document_type=original.document_type,
                        status=original.status,
                        page_number=original.page_number,
                        block_id=original.block_id,
                        score=round(float(score), 6) if score else original.score,
                        excerpt=original.excerpt,
                        ocr_confidence=original.ocr_confidence,
                        source_type=original.source_type,
                    )
                )

        return reranked[:top_k]

    except TimeoutError:
        logger.debug("Reranker timed out for query: %s", query[:100])
        return candidates[:top_k]
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        logger.debug("Reranker request failed: %s", exc)
        return candidates[:top_k]
    except Exception as exc:
        logger.warning("Unexpected reranker error: %s", exc)
        return candidates[:top_k]


def _rerank_local_sync(
    query: str,
    candidates: list[SearchResult],
    top_k: int,
) -> list[SearchResult]:
    """Synchronous in-process rerank. Runs in a worker thread from the
    async ``rerank()`` to avoid blocking the event loop on GPU work."""
    reranker = get_local_reranker()
    passages = [getattr(c, "full_text", None) or c.excerpt for c in candidates]
    scores = reranker.score(query, passages)
    order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    reranked: list[SearchResult] = []
    for idx in order[:top_k]:
        original = candidates[idx]
        score = scores[idx]
        reranked.append(
            original.__class__(
                document_id=original.document_id,
                original_filename=original.original_filename,
                document_type=original.document_type,
                status=original.status,
                page_number=original.page_number,
                block_id=original.block_id,
                score=round(float(score), 6),
                excerpt=original.excerpt,
                ocr_confidence=original.ocr_confidence,
                source_type=original.source_type,
            )
        )
    return reranked


def rerank_sync(
    query: str,
    candidates: list[SearchResult],
    top_k: int = 5,
) -> list[SearchResult]:
    """Synchronous wrapper for rerank()."""
    if len(candidates) <= MIN_CANDIDATES_FOR_RERANK:
        return candidates[:top_k]
    if settings.reranker_local_model.strip():
        try:
            return _rerank_local_sync(query, candidates, top_k)
        except Exception as exc:
            logger.warning("Local reranker failed, falling back: %s", exc)
            return candidates[:top_k]
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(rerank(query, candidates, top_k))
    # Already in an async context (e.g. a FastAPI async endpoint that called
    # search_hybrid synchronously). ``asyncio.run`` refuses to start a new loop
    # here, so bridge the coroutine onto the running loop and block for it.
    future = asyncio.run_coroutine_threadsafe(rerank(query, candidates, top_k), loop)
    return future.result()
