from __future__ import annotations

import asyncio
import hashlib
import math
import re
import time
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx

from app.core.config import settings
from app.services.cache import cache_service
from app.services.metrics import track_embedding_latency, track_cache_hit, track_cache_miss

if TYPE_CHECKING:
    pass

EMBEDDING_DIMENSIONS = int(settings.embedding_dimensions) if hasattr(settings, 'embedding_dimensions') and settings.embedding_dimensions else 768
TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
EMBEDDING_CACHE_TTL = 3600
BATCH_SIZE = 32
MAX_CONCURRENT_BATCHES = 4


class EmbeddingProviderError(RuntimeError):
    pass


@dataclass
class OpenAICompatibleEmbeddingClient:
    base_url: str
    model: str
    api_key: str | None = None
    dimensions: int = EMBEDDING_DIMENSIONS
    timeout_seconds: float = 30.0
    transport: httpx.BaseTransport | None = None

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        with httpx.Client(timeout=self.timeout_seconds, transport=self.transport) as client:
            response = client.post(
                _embedding_endpoint(self.base_url),
                headers=headers,
                json={"model": self.model, "input": texts},
            )
            response.raise_for_status()

        payload = response.json()
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

    async def embed_many_async(self, texts: list[str]) -> list[list[float]]:
        """Async version of embed_many for better performance in async contexts."""
        if not texts:
            return []
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                _embedding_endpoint(self.base_url),
                headers=headers,
                json={"model": self.model, "input": texts},
            )
            response.raise_for_status()

        payload = response.json()
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


def _embedding_cache_key(text: str, dimensions: int) -> str:
    namespace = "|".join(
        [
            settings.embedding_provider.lower().strip(),
            settings.embedding_base_url.strip() or settings.ai_base_url.strip(),
            settings.embedding_model.strip(),
            f"{OpenAICompatibleEmbeddingClient.__module__}.{OpenAICompatibleEmbeddingClient.__qualname__}",
            str(dimensions),
        ]
    )
    content = f"{namespace}:{text}"
    return f"embedding:{hashlib.md5(content.encode()).hexdigest()}"


def embed_text(text: str, dimensions: int | None = None) -> list[float]:
    return embed_many([text], dimensions=dimensions)[0]


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
        cache_key = _embedding_cache_key(text, vector_dimensions)
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
        embeddings = _generate_embeddings_batch(
            uncached_texts, provider, vector_dimensions
        )
        start = time.perf_counter()
        for idx, emb in zip(uncached_indices, embeddings):
            cached[idx] = emb
            cache_key = _embedding_cache_key(text_list[idx], vector_dimensions)
            cache_service.set(cache_key, emb, EMBEDDING_CACHE_TTL)
        track_embedding_latency(time.perf_counter() - start)

    return cached


async def embed_many_async(texts: Iterable[str], dimensions: int | None = None) -> list[list[float]]:
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
        cache_key = _embedding_cache_key(text, vector_dimensions)
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
            cache_key = _embedding_cache_key(text_list[idx], vector_dimensions)
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
                    batch = texts[i:i + BATCH_SIZE]
                    batch_embeddings = client.embed_many(batch)
                    all_embeddings.extend(batch_embeddings)

                return all_embeddings
            except Exception as exc:
                if not settings.embedding_fallback_to_hash:
                    raise EmbeddingProviderError(
                        f"Embedding provider failed at {base_url}: {exc}"
                    ) from exc
                return [embed_text_hash(t, dimensions) for t in texts]
        else:
            return [embed_text_hash(t, dimensions) for t in texts]
    else:
        return [embed_text_hash(t, dimensions) for t in texts]


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
                batches = [texts[i:i + BATCH_SIZE] for i in range(0, len(texts), BATCH_SIZE)]
                
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
                        if not settings.embedding_fallback_to_hash:
                            raise result
                        # Fallback for failed batch
                        batch_idx = len(all_embeddings) // BATCH_SIZE
                        start = batch_idx * BATCH_SIZE
                        batch_texts = texts[start:start + BATCH_SIZE]
                        all_embeddings.extend([embed_text_hash(t, dimensions) for t in batch_texts])
                    else:
                        all_embeddings.extend(result)
                
                return all_embeddings
            except Exception as exc:
                if not settings.embedding_fallback_to_hash:
                    raise EmbeddingProviderError(
                        f"Embedding async provider failed at {base_url}: {exc}"
                    ) from exc
                return [embed_text_hash(t, dimensions) for t in texts]
        else:
            return [embed_text_hash(t, dimensions) for t in texts]
    else:
        return [embed_text_hash(t, dimensions) for t in texts]


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
        "openai_compatible",
    }


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
    return [f"ng:{token[index:index + 3]}" for index in range(len(token) - 2)]


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
