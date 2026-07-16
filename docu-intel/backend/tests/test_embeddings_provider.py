import json

import httpx
import pytest

from app.core.config import settings
from app.services import embeddings

from app.services.embeddings import EMBEDDING_DIMENSIONS, EmbeddingProviderError, OpenAICompatibleEmbeddingClient, embed_many, embed_text


def test_openai_compatible_embedding_client_posts_to_local_embeddings_endpoint():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        body = json.loads(request.content.decode("utf-8"))
        assert str(request.url) == "http://embedding.local:1234/v1/embeddings"
        assert body == {"model": "bge-m3", "input": ["pedido ABC123", "plano salon"]}
        assert request.headers["authorization"] == "Bearer local-key"
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 0, "embedding": [1, 2, 3, 4]},
                    {"index": 1, "embedding": [3, 4, 5, 6]},
                ]
            },
        )

    client = OpenAICompatibleEmbeddingClient(
        base_url="http://embedding.local:1234/v1",
        model="bge-m3",
        api_key="local-key",
        dimensions=4,
        transport=httpx.MockTransport(handler),
    )

    assert client.embed_many(["pedido ABC123", "plano salon"]) == [
        [1.0, 2.0, 3.0, 4.0],
        [3.0, 4.0, 5.0, 6.0],
    ]
    assert len(requests) == 1


def test_embedding_dimension_mismatch_fails_fast(monkeypatch):
    from app.services.embeddings import EmbeddingProviderError as CurrentEmbeddingProviderError
    from app.services.embeddings import coerce_embedding_dimensions
    from app.core.config import settings

    monkeypatch.setattr(settings, "embedding_allow_dimension_coercion", False)

    with pytest.raises(CurrentEmbeddingProviderError, match="dimension mismatch"):
        coerce_embedding_dimensions([1, 2], 4)


def test_embedding_dimension_migration_flag_keeps_legacy_coercion(monkeypatch):
    from app.services.embeddings import coerce_embedding_dimensions

    if not hasattr(settings, "embedding_allow_dimension_coercion"):
        pytest.fail("migration flag embedding_allow_dimension_coercion is missing")

    monkeypatch.setattr(settings, "embedding_allow_dimension_coercion", True)

    assert coerce_embedding_dimensions([1, 2], 4) == [1.0, 2.0, 0.0, 0.0]
    assert coerce_embedding_dimensions([1, 2, 3, 4, 5], 4) == [1.0, 2.0, 3.0, 4.0]


def test_embed_many_uses_configured_local_openai_provider(monkeypatch):
    calls: list[tuple[str, str, str | None, int, list[str]]] = []

    class FakeClient:
        def __init__(self, *, base_url: str, model: str, api_key: str | None, dimensions: int, timeout_seconds: float):
            self.base_url = base_url
            self.model = model
            self.api_key = api_key
            self.dimensions = dimensions

        def embed_many(self, texts: list[str]) -> list[list[float]]:
            calls.append((self.base_url, self.model, self.api_key, self.dimensions, texts))
            return [[0.25, 0.5, 0.75, 1.0] for _ in texts]

    monkeypatch.setattr(embeddings, "OpenAICompatibleEmbeddingClient", FakeClient)
    monkeypatch.setattr(settings, "embedding_provider", "local_openai_compatible")
    monkeypatch.setattr(settings, "embedding_base_url", "http://embedding.local:1234/v1")
    monkeypatch.setattr(settings, "embedding_model", "bge-m3")
    monkeypatch.setattr(settings, "embedding_api_key", "local-key")
    monkeypatch.setattr(settings, "embedding_dimensions", 4)
    # This unit test exercises provider selection, not Redis persistence.
    # A previous test run can legitimately have cached the same fixture text.
    monkeypatch.setattr(embeddings.cache_service, "get", lambda _key: None)
    monkeypatch.setattr(embeddings.cache_service, "set", lambda *_args, **_kwargs: True)

    assert embed_many(["uno", "dos"]) == [[0.25, 0.5, 0.75, 1.0], [0.25, 0.5, 0.75, 1.0]]
    assert calls == [("http://embedding.local:1234/v1", "bge-m3", "local-key", 4, ["uno", "dos"])]


def test_embed_text_fails_fast_when_remote_provider_is_not_configured(monkeypatch):
    from app.services.embeddings import EmbeddingProviderError as CurrentEmbeddingProviderError

    monkeypatch.setattr(settings, "embedding_provider", "local_openai_compatible")
    monkeypatch.setattr(settings, "embedding_base_url", "")
    monkeypatch.setattr(settings, "ai_base_url", "")
    monkeypatch.setattr(settings, "embedding_dimensions", EMBEDDING_DIMENSIONS)

    with pytest.raises(CurrentEmbeddingProviderError, match="requires EMBEDDING_BASE_URL"):
        embed_text("pedido referencia ABC123")
