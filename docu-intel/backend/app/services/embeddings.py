from __future__ import annotations

import asyncio
import hashlib
import math
import re
import threading
import time
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx

from app.core.config import settings
from app.services.cache import cache_service
from app.services.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpen,
)
from app.services.metrics import track_embedding_latency, track_cache_hit, track_cache_miss

if TYPE_CHECKING:
    pass

# EMB-DIM-1 (Sprint 2): the previous fallback to ``768`` was a
# silent dimension mismatch. If the operator's ``.env`` had
# ``EMBEDDING_DIMENSIONS=`` (empty value) the module would
# fall back to 768 dims while the pgvector column is hard-
# coded to 1024. ``coerce_embedding_dimensions`` would then
# raise, the embedding write would fail, and the operator
# would see a cryptic error. The new code uses the same
# default as the pgvector column (``1024``) so a missing
# config value is consistent with the database, not a
# silent failure.
EMBEDDING_DIMENSIONS = int(settings.embedding_dimensions or 1024)
TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
EMBEDDING_CACHE_TTL = 3600
BATCH_SIZE = 32
MAX_CONCURRENT_BATCHES = 4


class EmbeddingProviderError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Circuit breaker for the remote embedding endpoint.
#
# Why a module-level singleton:
# - Multiple workers and FastAPI threads call ``OpenAICompatibleEmbeddingClient``
#   concurrently. Sharing one breaker gives the whole process a unified view
#   of "the embedding service is down", instead of every thread tripping
#   independently after its own 5 failures.
# - The thresholds come from the existing ``ai_circuit_breaker_*`` settings
#   so the AI and embedding breakers trip at the same rate. The ``name``
#   is a Prometheus label so the metrics UI can distinguish them.
# - The breaker is created lazily on first use to avoid importing it at
#   module-import time (settings are still warming up at that point).
# ---------------------------------------------------------------------------
_embedding_breaker: CircuitBreaker | None = None
_embedding_breaker_lock = threading.Lock()


def _get_embedding_breaker() -> CircuitBreaker:
    global _embedding_breaker
    if _embedding_breaker is not None:
        return _embedding_breaker
    with _embedding_breaker_lock:
        if _embedding_breaker is None:
            _embedding_breaker = CircuitBreaker(
                fail_max=int(getattr(settings, "ai_circuit_breaker_failures", 3)),
                reset_timeout=float(getattr(settings, "ai_circuit_breaker_reset_seconds", 30.0)),
                name="embeddings",
            )
    return _embedding_breaker


def reset_embedding_breaker() -> None:
    """Test/admin helper: force the embedding breaker back to CLOSED."""
    global _embedding_breaker
    if _embedding_breaker is not None:
        _embedding_breaker.reset()


@dataclass
class OpenAICompatibleEmbeddingClient:
    base_url: str
    model: str
    api_key: str | None = None
    dimensions: int = EMBEDDING_DIMENSIONS
    timeout_seconds: float = 30.0
    transport: httpx.BaseTransport | None = None
    breaker: CircuitBreaker | None = None  # injectable for tests

    def _do_request(self, client: httpx.Client, headers: dict, payload: dict) -> dict:
        try:
            response = client.post(
                _embedding_endpoint(self.base_url),
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            # Convert transport/HTTP errors into EmbeddingProviderError so
            # the circuit breaker can count them as failures. Without this
            # wrap, ``httpx.HTTPStatusError`` (4xx/5xx) would propagate
            # through the breaker and the breaker would not see it as a
            # failure (it only counts ``RuntimeError``-like signals by
            # accident — better to be explicit).
            raise EmbeddingProviderError(f"Embedding endpoint request failed: {exc}") from exc
        return response.json()

    def _parse_payload(self, payload: dict, texts: list[str]) -> list[list[float]]:
        data = payload.get("data")
        if not isinstance(data, list):
            raise EmbeddingProviderError("Embedding response does not contain a data list")
        indexed_items = sorted(enumerate(data), key=lambda item: item[1].get("index", item[0]))
        vectors = [
            coerce_embedding_dimensions(item.get("embedding"), self.dimensions)
            for _, item in indexed_items
            if isinstance(item, dict)
        ]
        if len(vectors) != len(texts):
            raise EmbeddingProviderError("Embedding response length does not match requested texts")
        return vectors

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {"model": self.model, "input": texts}
        breaker = self.breaker or _get_embedding_breaker()

        def _call() -> dict:
            with httpx.Client(timeout=self.timeout_seconds, transport=self.transport) as client:
                return self._do_request(client, headers, payload)

        try:
            response_payload = breaker.call(_call)
        except CircuitBreakerOpen:
            # Service is known-down; surface as a provider error so the
            # caller's existing fallback-to-hash path handles it.
            raise EmbeddingProviderError(f"Embedding circuit '{breaker.name}' is OPEN")
        return self._parse_payload(response_payload, texts)

    async def embed_many_async(self, texts: list[str]) -> list[list[float]]:
        """Async version of embed_many for better performance in async contexts.

        The circuit breaker is shared with the sync path. We re-use the
        sync ``_do_request`` by offloading it to a worker thread, which
        keeps the event loop free for the rest of the request handler.
        """
        if not texts:
            return []
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {"model": self.model, "input": texts}
        breaker = self.breaker or _get_embedding_breaker()

        def _call() -> dict:
            with httpx.Client(timeout=self.timeout_seconds, transport=self.transport) as client:
                return self._do_request(client, headers, payload)

        try:
            # Offload to a worker thread: the breaker is fast (microseconds)
            # but the HTTP call is the slow part, so doing both in the
            # worker thread keeps the event loop responsive.
            response_payload = await asyncio.to_thread(breaker.call, _call)
        except CircuitBreakerOpen:
            raise EmbeddingProviderError(f"Embedding circuit '{breaker.name}' is OPEN")
        return self._parse_payload(response_payload, texts)


def _embedding_cache_key(text: str, dimensions: int, *, role: str = "passage") -> str:
    namespace = "|".join(
        [
            settings.embedding_provider.lower().strip(),
            settings.embedding_base_url.strip() or settings.ai_base_url.strip(),
            settings.embedding_model.strip(),
            f"{OpenAICompatibleEmbeddingClient.__module__}.{OpenAICompatibleEmbeddingClient.__qualname__}",
            str(dimensions),
            role,
        ]
    )
    content = f"{namespace}:{text}"
    return f"embedding:{hashlib.md5(content.encode()).hexdigest()}"


def embed_text(text: str, dimensions: int | None = None) -> list[float]:
    return embed_many([text], dimensions=dimensions)[0]


async def embed_text_async(text: str, dimensions: int | None = None) -> list[float]:
    """Async wrapper around :func:`embed_text` for FastAPI request handlers.

    The underlying embedding providers are CPU/IO bound but synchronous. We
    offload the call to a worker thread so the event loop is not blocked while
    a request is computing an embedding.
    """
    return await asyncio.to_thread(embed_text, text, dimensions)


async def embed_query_text_async(text: str, dimensions: int | None = None) -> list[float]:
    """Async wrapper around :func:`embed_query_text`.

    Query embedding is on the critical path of every ``/ai/ask`` request, so
    we offload the CPU/IO work to a thread and yield to the event loop.
    """
    return await asyncio.to_thread(embed_query_text, text, dimensions)


def embed_query_text(text: str, dimensions: int | None = None) -> list[float]:
    """Embed a user query with query-side semantics when the provider needs it.

    The public ``embed_many`` path remains passage-mode because it is used by
    indexing. OpenAI-compatible providers do not distinguish query/passage, so
    they keep the existing behavior.
    """
    vector_dimensions = dimensions or _configured_dimensions()
    provider = settings.embedding_provider.lower().strip()
    if provider != "local_sentence_transformers":
        return embed_text(text, dimensions=vector_dimensions)

    cache_key = _embedding_cache_key(text, vector_dimensions, role="query")
    cached = cache_service.get(cache_key)
    if cached is not None:
        track_cache_hit()
        return cached
    track_cache_miss()

    try:
        vector = coerce_embedding_dimensions(
            get_local_embedding_client().embed_query(text),
            vector_dimensions,
        )
    except Exception as exc:
        raise EmbeddingProviderError(
            f"Local sentence-transformers query embedding failed: {exc}"
        ) from exc

    cache_service.set(cache_key, vector, EMBEDDING_CACHE_TTL)
    return vector


def embed_many(texts: Iterable[str], dimensions: int | None = None) -> list[list[float]]:
    """Synchronous embedding generation with batch processing and caching."""
    text_list = list(texts)
    if not text_list:
        return []

    vector_dimensions = dimensions or _configured_dimensions()
    provider = settings.embedding_provider.lower().strip()

    # Check cache for all texts
    cached = []
    uncached_indices = []
    uncached_texts = []

    for i, text in enumerate(text_list):
        cache_key = _embedding_cache_key(text, vector_dimensions, role="passage")
        cached_val = cache_service.get(cache_key)
        if cached_val is not None:
            cached.append(cached_val)
            track_cache_hit()
        else:
            cached.append(None)
            uncached_indices.append(i)
            uncached_texts.append(text)
            track_cache_miss()

    if uncached_texts:
        embeddings = _generate_embeddings_batch(uncached_texts, provider, vector_dimensions)
        start = time.perf_counter()
        for idx, emb in zip(uncached_indices, embeddings):
            cached[idx] = emb
            cache_key = _embedding_cache_key(text_list[idx], vector_dimensions, role="passage")
            cache_service.set(cache_key, emb, EMBEDDING_CACHE_TTL)
        track_embedding_latency(time.perf_counter() - start)

    return cached


async def embed_many_async(
    texts: Iterable[str], dimensions: int | None = None
) -> list[list[float]]:
    """Async embedding generation with batch processing and concurrent requests."""
    text_list = list(texts)
    if not text_list:
        return []

    vector_dimensions = dimensions or _configured_dimensions()
    provider = settings.embedding_provider.lower().strip()

    # Check cache for all texts
    cached = []
    uncached_indices = []
    uncached_texts = []

    for i, text in enumerate(text_list):
        cache_key = _embedding_cache_key(text, vector_dimensions, role="passage")
        cached_val = cache_service.get(cache_key)
        if cached_val is not None:
            cached.append(cached_val)
            track_cache_hit()
        else:
            cached.append(None)
            uncached_indices.append(i)
            uncached_texts.append(text)
            track_cache_miss()

    if uncached_texts:
        start = time.perf_counter()
        embeddings = await _generate_embeddings_batch_async(
            uncached_texts, provider, vector_dimensions
        )
        track_embedding_latency(time.perf_counter() - start)

        for idx, emb in zip(uncached_indices, embeddings):
            cached[idx] = emb
            cache_key = _embedding_cache_key(text_list[idx], vector_dimensions, role="passage")
            cache_service.set(cache_key, emb, EMBEDDING_CACHE_TTL)

    return cached


def _generate_embeddings_batch(
    texts: list[str],
    provider: str,
    dimensions: int,
) -> list[list[float]]:
    """Generate embeddings in batches for better throughput."""
    if provider in {"local_openai_compatible", "openai_compatible"}:
        base_url = settings.embedding_base_url.strip() or settings.ai_base_url.strip()
        if base_url:
            try:
                client = OpenAICompatibleEmbeddingClient(
                    base_url=base_url,
                    model=settings.embedding_model,
                    api_key=settings.embedding_api_key or settings.ai_api_key or None,
                    dimensions=dimensions,
                    timeout_seconds=settings.embedding_timeout_seconds,
                )

                # Process in batches
                all_embeddings = []
                for i in range(0, len(texts), BATCH_SIZE):
                    batch = texts[i : i + BATCH_SIZE]
                    batch_embeddings = client.embed_many(batch)
                    all_embeddings.extend(batch_embeddings)

                return all_embeddings
            except Exception as exc:
                raise EmbeddingProviderError(
                    f"Embedding provider failed at {base_url}: {exc}"
                ) from exc
        else:
            raise EmbeddingProviderError(
                "Embedding provider requires EMBEDDING_BASE_URL or AI_BASE_URL"
            )
    if provider == "local_sentence_transformers":
        try:
            client = get_local_embedding_client()
            return [
                coerce_embedding_dimensions(vector, dimensions)
                for vector in client.embed_many(texts)
            ]
        except Exception as exc:
            raise EmbeddingProviderError(
                f"Local sentence-transformers embedding failed: {exc}"
            ) from exc
    if provider in {"local", "local_hash"}:
        return [embed_text_hash(t, dimensions) for t in texts]
    raise EmbeddingProviderError(f"Unsupported embedding provider: {provider}")


async def _generate_embeddings_batch_async(
    texts: list[str],
    provider: str,
    dimensions: int,
) -> list[list[float]]:
    """Generate embeddings asynchronously with concurrent batch processing."""
    if provider in {"local_openai_compatible", "openai_compatible"}:
        base_url = settings.embedding_base_url.strip() or settings.ai_base_url.strip()
        if base_url:
            try:
                client = OpenAICompatibleEmbeddingClient(
                    base_url=base_url,
                    model=settings.embedding_model,
                    api_key=settings.embedding_api_key or settings.ai_api_key or None,
                    dimensions=dimensions,
                    timeout_seconds=settings.embedding_timeout_seconds,
                )

                # Process batches concurrently
                batches = [texts[i : i + BATCH_SIZE] for i in range(0, len(texts), BATCH_SIZE)]

                # Limit concurrent requests
                semaphore = asyncio.Semaphore(MAX_CONCURRENT_BATCHES)

                async def process_batch(batch: list[str]) -> list[list[float]]:
                    async with semaphore:
                        return await client.embed_many_async(batch)

                tasks = [process_batch(batch) for batch in batches]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                all_embeddings = []
                for result in results:
                    if isinstance(result, Exception):
                        raise result
                    else:
                        all_embeddings.extend(result)

                return all_embeddings
            except Exception as exc:
                raise EmbeddingProviderError(
                    f"Embedding async provider failed at {base_url}: {exc}"
                ) from exc
        else:
            raise EmbeddingProviderError(
                "Embedding provider requires EMBEDDING_BASE_URL or AI_BASE_URL"
            )
    if provider == "local_sentence_transformers":
        # The local path is CPU-bound during encode (PyTorch releases the
        # GIL inside the kernel), so we run it in the default executor
        # to avoid blocking the event loop.
        loop = asyncio.get_running_loop()
        try:
            vectors = await loop.run_in_executor(
                None, get_local_embedding_client().embed_many, texts
            )
            return [coerce_embedding_dimensions(vector, dimensions) for vector in vectors]
        except Exception as exc:
            raise EmbeddingProviderError(
                f"Local sentence-transformers embedding failed: {exc}"
            ) from exc
    if provider in {"local", "local_hash"}:
        return [embed_text_hash(t, dimensions) for t in texts]
    raise EmbeddingProviderError(f"Unsupported embedding provider: {provider}")


def embed_text_hash(text: str, dimensions: int = EMBEDDING_DIMENSIONS) -> list[float]:
    vector = [0.0] * dimensions
    tokens = _tokenize(text)
    if not tokens:
        return vector

    for token in tokens:
        _add_feature(vector, token, 1.0)
        for ngram in _char_ngrams(token):
            _add_feature(vector, ngram, 0.35)

    return _normalize(vector)


def should_create_embeddings() -> bool:
    return settings.embedding_provider.lower() in {
        "local",
        "local_hash",
        "local_openai_compatible",
        "local_sentence_transformers",
        "openai_compatible",
    }


# ---------------------------------------------------------------------------
# In-process embedding via sentence-transformers
# ---------------------------------------------------------------------------
# Used when ``embedding_provider == "local_sentence_transformers"``. Loads
# the configured model (default: IBM Granite 311M multilingual) on the
# configured device (default: cuda) on first use, then reuses the loaded
# model for every subsequent call. The model is downloaded from
# HuggingFace on first init (~600 MB for Granite 311M).
#
# Granite 311M uses ASYMMETRIC embeddings: queries get a "query: " prefix
# and passages get a "passage: " prefix. sentence-transformers handles this
# via the ``prompt`` argument at encode time, so callers must pass the
# right role. The provider exposes two methods — ``embed_query`` and
# ``embed_passages`` — that wrap ``SentenceTransformer.encode`` with the
# correct prompt. The bulk path ``embed_many`` defaults to passage mode
# (it's what the indexing pipeline needs).


# Prompts used by IBM Granite embedding. The model card mandates these
# exact strings for the multilingual R2 release.
_GRANITE_QUERY_PROMPT = "query: "
_GRANITE_PASSAGE_PROMPT = "passage: "
# Models that use asymmetric query/passage prompts. Add more here as we
# onboard other asymmetric embedding models.
_ASYMMETRIC_MODELS: set[str] = {
    "ibm-granite/granite-embedding-311m-multilingual-r2",
    "ibm-granite/granite-embedding-125m-english",
    "ibm-granite/granite-embedding-107m-multilingual",
}


def _query_prompt_for(model_name: str) -> str | None:
    """Return the query-side prompt for asymmetric models, or ``None``
    for symmetric models (BGE, E5-base, etc.) which take a single
    prefix for both sides or no prefix at all.

    EMB-PROV-1 (Sprint 2): the previous implementation also
    matched any model whose name started with
    ``"ibm-granite/granite-embedding"`` (a broad ``startswith``
    fallback). The fallback was a footgun: if a future
    asymmetric model was published with a name that happened
    to start with that prefix, it would silently receive the
    IBM Granite prefix — which might or might not match its
    own contract. The new code uses the explicit allow-list
    only; to onboard a new asymmetric model, add its name to
    :data:`_ASYMMETRIC_MODELS`.
    """
    if model_name in _ASYMMETRIC_MODELS:
        return _GRANITE_QUERY_PROMPT
    return None


def _passage_prompt_for(model_name: str) -> str | None:
    if model_name in _ASYMMETRIC_MODELS:
        return _GRANITE_PASSAGE_PROMPT
    return None


@dataclass
class LocalSentenceTransformerEmbeddingClient:
    """In-process sentence-transformers embedding client.

    Loads the model lazily on the first call. The download + GPU upload
    can take 10-30 s the first time; subsequent calls are tens of ms
    per batch on an RTX 4070.

    The model is loaded in a background thread (same pattern as
    PaddleOCR) so the constructor never blocks the caller.
    """

    model_name: str
    device: str = "cuda"
    batch_size: int = 32
    max_length: int = 512
    normalize: bool = True  # cosine-similarity friendly

    _model: object = None  # SentenceTransformer | None
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
            from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]

            # OPS-FALLBACK-1: try the configured device first
            # (typically ``cuda``). If the load fails because the
            # host has no GPU / no torch CUDA build, fall back to
            # CPU. Embeddings still work, just slower.
            try:
                self._model = SentenceTransformer(
                    self.model_name,
                    device=self.device,
                    trust_remote_code=False,
                )
                import logging

                logging.getLogger("app.services.embeddings").info(
                    "Local embedding model loaded: name=%s device=%s",
                    self.model_name,
                    self.device,
                )
            except Exception as exc:  # noqa: BLE001
                if self.device == "cpu":
                    # Already on the safest path; nothing to fall
                    # back to.
                    self._init_error = exc
                    raise
                import logging

                logging.getLogger("app.services.embeddings").warning(
                    "Local embedding model failed to load on device=%s (%s); "
                    "falling back to CPU. The platform keeps working, "
                    "embeddings are just slower.",
                    self.device,
                    exc,
                )
                self.device = "cpu"
                self._model = SentenceTransformer(
                    self.model_name,
                    device="cpu",
                    trust_remote_code=False,
                )
            self._model.max_seq_length = self.max_length
        return self._model

    @property
    def dimensions(self) -> int:
        """Embedding dimensionality. We load the model to query it the
        first time; after that it's cached on the instance."""
        model = self._ensure_loaded()
        return int(model.get_sentence_embedding_dimension())

    def embed_query(self, text: str) -> list[float]:
        return self._encode_one(text, role="query")

    def embed_passage(self, text: str) -> list[float]:
        return self._encode_one(text, role="passage")

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        return self._encode_many(texts, role="query")

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return self._encode_many(texts, role="passage")

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        """Bulk embed in passage mode (the indexing pipeline's default)."""
        return self._encode_many(texts, role="passage")

    def _encode_one(self, text: str, *, role: str) -> list[float]:
        return self._encode_many([text], role=role)[0]

    def _encode_many(self, texts: list[str], *, role: str) -> list[list[float]]:
        if not texts:
            return []
        model = self._ensure_loaded()
        prompt = (
            _query_prompt_for(self.model_name)
            if role == "query"
            else _passage_prompt_for(self.model_name)
        )
        # sentence-transformers' encode handles ``prompt`` for asymmetric
        # models; for symmetric models it should be ``None`` to avoid
        # adding an unwanted prefix.
        kwargs: dict[str, object] = {
            "batch_size": self.batch_size,
            "convert_to_numpy": True,
            "normalize_embeddings": self.normalize,
            "show_progress_bar": False,
        }
        if prompt is not None:
            kwargs["prompt"] = prompt
        vectors = model.encode(texts, **kwargs)
        return [v.tolist() for v in vectors]


# Module-level singleton keyed by (model_name, device) so the same worker
# reuses one model across calls. The factory returns the right one.
_local_embedding_clients: dict[tuple[str, str], LocalSentenceTransformerEmbeddingClient] = {}
_local_embedding_lock = threading.Lock()


def get_local_embedding_client() -> LocalSentenceTransformerEmbeddingClient:
    """Return the worker-scoped singleton local embedding client.

    Reads ``embedding_local_model`` / ``embedding_local_device`` /
    ``embedding_local_batch_size`` / ``embedding_local_max_length`` from
    settings. The first call downloads the model from HuggingFace.
    """
    key = (settings.embedding_local_model, settings.embedding_local_device)
    client = _local_embedding_clients.get(key)
    if client is not None:
        return client
    with _local_embedding_lock:
        client = _local_embedding_clients.get(key)
        if client is not None:
            return client
        client = LocalSentenceTransformerEmbeddingClient(
            model_name=settings.embedding_local_model,
            device=settings.embedding_local_device,
            batch_size=settings.embedding_local_batch_size,
            max_length=settings.embedding_local_max_length,
        )
        _local_embedding_clients[key] = client
    return client


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    size = min(len(left), len(right))
    numerator = sum(left[index] * right[index] for index in range(size))
    left_norm = math.sqrt(sum(value * value for value in left[:size]))
    right_norm = math.sqrt(sum(value * value for value in right[:size]))
    norm_product = left_norm * right_norm
    if norm_product < 1e-10:
        return 0.0
    return numerator / norm_product


def _tokenize(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKD", text.lower())
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return TOKEN_RE.findall(ascii_text)


def _char_ngrams(token: str) -> list[str]:
    if len(token) <= 3:
        return [f"ng:{token}"]
    return [f"ng:{token[index : index + 3]}" for index in range(len(token) - 2)]


def _add_feature(vector: list[float], feature: str, weight: float) -> None:
    digest = hashlib.sha256(feature.encode("utf-8")).digest()
    index = int.from_bytes(digest[:4], "big") % len(vector)
    sign = 1.0 if digest[4] % 2 == 0 else -1.0
    vector[index] += sign * weight


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def coerce_embedding_dimensions(raw_embedding: object, dimensions: int) -> list[float]:
    if not isinstance(raw_embedding, list):
        raise EmbeddingProviderError("Embedding item is not a list")
    vector = [float(value) for value in raw_embedding]
    if len(vector) != dimensions and not settings.embedding_allow_dimension_coercion:
        raise EmbeddingProviderError(
            f"Embedding dimension mismatch: got {len(vector)}, expected {dimensions}. "
            "Check EMBEDDING_MODEL/EMBEDDING_DIMENSIONS or enable "
            "EMBEDDING_ALLOW_DIMENSION_COERCION only during a controlled migration."
        )
    if len(vector) < dimensions:
        vector.extend([0.0] * (dimensions - len(vector)))
    return vector[:dimensions]


def _embedding_endpoint(base_url: str) -> str:
    clean = base_url.rstrip("/")
    if clean.endswith("/embeddings"):
        return clean
    return f"{clean}/embeddings"


def _configured_dimensions() -> int:
    dimensions = int(settings.embedding_dimensions or EMBEDDING_DIMENSIONS)
    return max(1, dimensions)


def chunks_needing_model_migration(db) -> int:
    """Count how many chunks have an ``embedding_model_version``
    that differs from the current ``settings.embedding_model``.

    This is the cheap check the periodic re-embed sweep runs
    every tick to decide whether to kick off a migration batch.
    The actual migration is done by
    :func:`app.services.document_embedding_pipeline.reembed_document`.
    """
    from app.models import DocumentChunk

    current = settings.embedding_model
    if not current:
        return 0
    from sqlalchemy import func, select

    count = db.scalar(
        select(func.count())
        .select_from(DocumentChunk)
        .where(
            DocumentChunk.embedding_model_version.is_not(None),
            DocumentChunk.embedding_model_version != current,
        )
    )
    return int(count or 0)
