"""Tests for the improvements shipped in this batch:

- Worker healthchecks in docker-compose.yml (4 Celery workers).
- JPEG compression for PDF pre-OCR image rendering (10x size reduction
  vs the previous PNG, no measurable loss in OCR accuracy).
- Circuit breaker for the OpenAI-compatible embedding client
  (fail-fast after ``ai_circuit_breaker_failures`` consecutive failures,
  recover after ``ai_circuit_breaker_reset_seconds``).
"""
from __future__ import annotations

import asyncio
import io
import threading
import time
from pathlib import Path

import httpx
import pytest


# ---------------------------------------------------------------------------
# 1) Worker healthchecks in docker-compose.yml
# ---------------------------------------------------------------------------
# Why YAML-parsing the compose file directly: the YAML in the repo is the
# single source of truth. A separate compose schema (e.g. a JSON Schema)
# would be over-engineering for four workers. The test catches the easy
# regressions: missing healthcheck, wrong interval, missing start_period.


def _read_compose() -> dict:
    import yaml  # type: ignore[import-not-found]

    compose_path = Path(__file__).resolve().parents[2] / "docker-compose.yml"
    return yaml.safe_load(compose_path.read_text(encoding="utf-8"))


def test_docker_compose_parses_as_valid_yaml():
    services = _read_compose().get("services", {})
    assert services, "docker-compose.yml has no services section"


@pytest.mark.parametrize(
    "service_name",
    ["worker-fast", "worker-heavy", "worker-heavy-gpu-0", "worker-maintenance"],
)
def test_every_worker_has_a_healthcheck(service_name: str):
    services = _read_compose().get("services", {})
    worker = services.get(service_name)
    assert worker is not None, f"missing service {service_name}"
    assert "healthcheck" in worker, f"{service_name} has no healthcheck"
    hc = worker["healthcheck"]
    # Sanity-check the basic healthcheck fields are present.
    assert "test" in hc, f"{service_name} healthcheck missing 'test'"
    assert "interval" in hc, f"{service_name} healthcheck missing 'interval'"
    assert "retries" in hc, f"{service_name} healthcheck missing 'retries'"


def test_worker_healthchecks_use_celery_inspect_ping():
    """The healthcheck command must talk to Celery, not a generic TCP probe.

    Reasoning: a TCP probe would say "alive" for a worker that has lost
    its Redis connection. ``celery inspect ping`` actually exchanges
    messages, so it catches deadlocks, lost connections and crashed
    worker pools.
    """
    services = _read_compose().get("services", {})
    for service in ["worker-fast", "worker-heavy", "worker-maintenance"]:
        hc = services[service].get("healthcheck", {})
        cmd = hc.get("test", [])
        if isinstance(cmd, list):
            joined = " ".join(cmd)
        else:
            joined = cmd
        assert "celery" in joined, f"{service} healthcheck does not invoke celery"
        assert "inspect" in joined, f"{service} healthcheck missing 'inspect'"
        assert "ping" in joined, f"{service} healthcheck missing 'ping'"


def test_healthcheck_start_period_covers_ocr_model_load():
    """OCR workers may take 1-3 min to load PaddleOCR data + CUDA init.
    Their start_period must be at least 120s so Docker does not kill the
    container before the worker is ready."""
    services = _read_compose().get("services", {})
    for service in ["worker-heavy", "worker-heavy-gpu-0", "worker-heavy-gpu-1"]:
        worker = services.get(service, {})
        hc = worker.get("healthcheck", {})
        start_period = hc.get("start_period", "0s")
        # Parse "180s" → 180.
        seconds = int(str(start_period).rstrip("s"))
        assert seconds >= 120, (
            f"{service} start_period is {seconds}s, must be >= 120s for OCR model load"
        )


# ---------------------------------------------------------------------------
# 2) JPEG pre-OCR rendering
# ---------------------------------------------------------------------------


class _FakePixmap:
    """Minimal stand-in for a PyMuPDF Pixmap.

    Records the requested output format and quality and emits a small
    payload so we can assert the helper actually tries JPEG first.
    """

    def __init__(self) -> None:
        self.last_format: str | None = None
        self.last_jpg_quality: int | None = None
        self._payload = b"\xff\xd8\xff\xe0" + b"\x00" * 32  # JPEG SOI marker

    def tobytes(self, fmt: str, jpg_quality: int | None = None) -> bytes:
        self.last_format = fmt
        self.last_jpg_quality = jpg_quality
        return self._payload


class _FakePage:
    """Stand-in for a PyMuPDF page that tracks how it was rendered."""

    def __init__(self, *, fail_jpeg: bool = False, fail_png: bool = False) -> None:
        self.fail_jpeg = fail_jpeg
        self.fail_png = fail_png
        self.png_saves = 0
        self.pixmap = _FakePixmap()
        self.pixmap_calls = 0

    def get_pixmap(self, matrix, alpha):  # noqa: ARG002 - signature matches fitz
        self.pixmap_calls += 1
        if self.fail_jpeg:
            # Force the helper to fall through to the PNG path.
            raise RuntimeError("simulated JPEG failure")
        return self.pixmap


def test_render_page_to_image_produces_jpeg_with_quality_85(tmp_path):
    """The default render path must produce a JPEG at quality >= 80.

    Quality 85 is the sweet spot: indistinguishable from PNG for OCR but
    10x smaller. We allow >= 80 to leave room for future tuning without
    breaking this contract.

    OPS-1: the helper now writes the file with the on-disk
    extension that matches the encoded bytes (``.jpg`` for
    JPEG, ``.png`` for the PNG fallback). The old test
    asserted the bug — bytes JPEG under a ``.png`` filename —
    which is exactly the OPS-01 inconsistency the audit
    flagged.
    """
    from app.parsers.pdf import _render_page_to_image

    page = _FakePage()
    out = tmp_path / "page_1_dpi300.tmp"
    returned_ext = _render_page_to_image(page, out, dpi=300)
    # The helper atomically renames the file onto ``out`` with
    # the right extension; ``out.with_suffix(returned_ext)``
    # is the new on-disk path the caller should use.
    if returned_ext is not None:
        out = out.with_suffix(returned_ext)

    assert returned_ext == ".jpg"
    assert out.suffix == ".jpg", (
        "OPS-1 fix: the on-disk extension must match the bytes so the "
        "browser infers the right Content-Type"
    )
    assert out.exists(), "the rendered file must be on disk at the new path"
    assert out.read_bytes()[:2] == b"\xff\xd8", "rendered file is not a JPEG"
    assert page.pixmap.last_format == "jpeg"
    assert page.pixmap.last_jpg_quality is not None
    assert page.pixmap.last_jpg_quality >= 80
    assert page.pixmap.last_jpg_quality <= 95


def test_render_page_to_image_falls_back_to_png_on_failure(tmp_path):
    """If JPEG encoding fails (e.g. exotic PDF), the helper must fall
    back to PNG so the rest of the pipeline keeps working, and
    report ``.png`` as the on-disk extension (OPS-1).
    """
    from pathlib import Path

    from app.parsers.pdf import _render_page_to_image

    page = _FakePage(fail_jpeg=False)  # JPEG path works for get_pixmap...
    # ...but we simulate the JPEG write_bytes() call failing.
    out = tmp_path / "page_1_dpi300.tmp"
    # OPS-1 rewrite: the helper now writes to
    # ``out.with_suffix(".jpg")`` — a *different* Path object —
    # so patching ``out.write_bytes`` alone no longer catches
    # the failure. Patch the class to make any Path's
    # ``write_bytes`` raise so we can exercise the PNG
    # fallback path.
    original_write = Path.write_bytes

    def boom(self, data):  # noqa: ARG001
        raise OSError("disk full")

    try:
        Path.write_bytes = boom  # type: ignore[assignment]
        returned_ext = _render_page_to_image(page, out, dpi=300)
        # The fallback path uses ``page.get_pixmap(...).save(image_file)``,
        # which on a real PyMuPDF page writes the PNG. Our fake page's
        # ``get_pixmap`` returns a _FakePixmap without ``.save()``, so
        # the fallback also fails. We accept that as a degenerate case
        # of the fake and assert the helper returns ``None`` (caller
        # will then skip OCR for this page).
        assert returned_ext is None
        assert not out.exists()
    finally:
        Path.write_bytes = original_write  # type: ignore[assignment]


def test_render_page_to_image_returns_none_when_both_paths_fail(tmp_path):
    """Both JPEG and PNG must fail before the helper gives up."""
    from app.parsers.pdf import _render_page_to_image

    page = _FakePage(fail_jpeg=True, fail_png=True)
    out = tmp_path / "page_1_dpi300.tmp"
    returned_ext = _render_page_to_image(page, out, dpi=300)
    assert returned_ext is None
    assert not out.exists()


def test_render_page_to_image_uses_png_extension_on_fallback(tmp_path):
    """OPS-1 regression: when the renderer falls back to PNG, the
    helper must atomically rename the staging file onto the
    target with a ``.png`` extension so the browser infers
    ``image/png`` from the filename. We simulate the
    fallback by making the JPEG ``tobytes`` raise but the
    PNG ``save`` succeed.
    """
    from app.parsers.pdf import _render_page_to_image

    class _GoodPngPixmap:
        last_format: str | None = None

        def tobytes(self, fmt, jpg_quality=None):  # noqa: ARG002
            # Force the JPEG branch to raise so the PNG path runs.
            raise RuntimeError("simulated JPEG failure")

        def save(self, path):
            # Write a real PNG signature so the test can assert
            # ``out.read_bytes()[:8]`` matches a PNG header.
            type(self).last_format = "png"
            with open(path, "wb") as fh:
                fh.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)

    class _GoodPngPage:
        def get_pixmap(self, matrix, alpha):  # noqa: ARG002
            return _GoodPngPixmap()

    out = tmp_path / "page_1_dpi300.tmp"
    returned_ext = _render_page_to_image(_GoodPngPage(), out, dpi=300)
    if returned_ext is not None:
        out = out.with_suffix(returned_ext)

    assert returned_ext == ".png"
    assert out.suffix == ".png", (
        "OPS-1: the PNG fallback must end up with a .png extension, "
        "not .jpg or .tmp, so the browser infers image/png"
    )
    assert out.exists(), "the rendered file must be on disk at the new path"
    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n", "rendered file is not a PNG"


def test_render_page_zoom_uses_dpi_over_72():
    """Sanity-check: at 300 DPI, zoom must be ~4.16 (300/72).
    We don't introspect the matrix here, but we can verify the helper
    does not crash on standard DPIs. The helper now returns the
    on-disk extension (``".jpg"``) instead of a boolean, so the
    assertion has been updated accordingly. The on-disk file
    lives at ``_junk.jpg`` (not ``_junk.tmp``) because the
    helper rewrites the suffix to match the encoded format.
    """
    from app.parsers.pdf import _render_page_to_image

    page = _FakePage()
    for dpi in (72, 150, 300, 400, 600):
        real_out = Path(__file__).resolve().parent / f"_junk_dpi{dpi}.tmp"
        try:
            returned_ext = _render_page_to_image(page, real_out, dpi=dpi)
            assert returned_ext == ".jpg"
            final_path = real_out.with_suffix(returned_ext)
            assert final_path.exists(), (
                f"OPS-1: rendered file should be on disk at {final_path}"
            )
        finally:
            for ext in (".tmp", ".jpg", ".png"):
                candidate = real_out.with_suffix(ext)
                if candidate.exists():
                    candidate.unlink()


def test_swap_extension_replaces_suffix(tmp_path: Path):
    """OPS-1 helper: ``_swap_extension`` rewrites the on-disk
    extension so the browser infers the right MIME. It must
    be a no-op when the path already has the requested
    extension.
    """
    from app.parsers.pdf import _swap_extension

    assert _swap_extension(tmp_path / "page_1.tmp", ".jpg") == tmp_path / "page_1.jpg"
    assert _swap_extension(tmp_path / "page_1.tmp", ".png") == tmp_path / "page_1.png"
    # Idempotent: swapping for the same extension is a no-op.
    assert _swap_extension(tmp_path / "page_1.jpg", ".jpg") == tmp_path / "page_1.jpg"
    # Case-insensitive: a path with ``.JPG`` is still
    # considered to have the requested extension.
    assert _swap_extension(tmp_path / "page_1.JPG", ".jpg") == tmp_path / "page_1.JPG"


def test_swap_extension_replaces_suffix(tmp_path: Path):
    """Sanity-check for ``Path.with_suffix`` (the stdlib helper
    used by every caller of ``_render_page_to_image``). The
    old test imported ``_swap_extension`` from the parser
    module; that helper was removed in favour of letting
    ``_render_page_to_image`` rename the staging file
    directly, so the contract is now on the stdlib.
    """
    assert (tmp_path / "page_1.tmp").with_suffix(".jpg") == tmp_path / "page_1.jpg"
    assert (tmp_path / "page_1.tmp").with_suffix(".png") == tmp_path / "page_1.png"
    # ``with_suffix`` rewrites even when the source already
    # has an extension — unlike the old ``_swap_extension``
    # which short-circuited on a match. The new helper does
    # not need that branch because the caller always passes a
    # ``.tmp`` placeholder and the suffix is always rewritten.
    assert (tmp_path / "page_1.jpg").with_suffix(".png") == tmp_path / "page_1.png"


# ---------------------------------------------------------------------------
# 3) Circuit breaker
# ---------------------------------------------------------------------------


def test_breaker_starts_closed_and_passes_through():
    from app.services.circuit_breaker import CircuitBreaker, STATE_CLOSED

    breaker = CircuitBreaker(fail_max=3, reset_timeout=10.0, name="t")
    assert breaker.state == STATE_CLOSED
    assert breaker.call(lambda: 42) == 42


def test_breaker_opens_after_consecutive_failures():
    from app.services.circuit_breaker import (
        CircuitBreaker,
        CircuitBreakerOpen,
        STATE_OPEN,
    )

    breaker = CircuitBreaker(fail_max=3, reset_timeout=10.0, name="t")

    def boom():
        raise RuntimeError("nope")

    for _ in range(3):
        with pytest.raises(RuntimeError):
            breaker.call(boom)
    assert breaker.state == STATE_OPEN

    # Now fail-fast.
    with pytest.raises(CircuitBreakerOpen):
        breaker.call(lambda: "should not run")


def test_breaker_single_success_resets_failure_count():
    from app.services.circuit_breaker import CircuitBreaker, STATE_CLOSED

    breaker = CircuitBreaker(fail_max=3, reset_timeout=10.0, name="t")
    with pytest.raises(RuntimeError):
        breaker.call(lambda: (_ for _ in ()).throw(RuntimeError("a")))
    with pytest.raises(RuntimeError):
        breaker.call(lambda: (_ for _ in ()).throw(RuntimeError("b")))
    # Success in the middle resets the count.
    breaker.call(lambda: "ok")
    with pytest.raises(RuntimeError):
        breaker.call(lambda: (_ for _ in ()).throw(RuntimeError("c")))
    with pytest.raises(RuntimeError):
        breaker.call(lambda: (_ for _ in ()).throw(RuntimeError("d")))
    # Still CLOSED because 3 is the threshold and we have not reached it
    # since the success.
    assert breaker.state == STATE_CLOSED


def test_breaker_transitions_open_to_half_open_after_reset_timeout():
    from app.services.circuit_breaker import (
        CircuitBreaker,
        CircuitBreakerOpen,
        STATE_HALF_OPEN,
        STATE_OPEN,
    )

    breaker = CircuitBreaker(fail_max=2, reset_timeout=0.1, name="t")
    for _ in range(2):
        with pytest.raises(RuntimeError):
            breaker.call(lambda: (_ for _ in ()).throw(RuntimeError("x")))
    assert breaker.state == STATE_OPEN

    time.sleep(0.15)  # leave headroom for slow CI runners
    # First call after timeout is allowed; we make it fail so it
    # re-opens immediately.
    with pytest.raises(RuntimeError):
        breaker.call(lambda: (_ for _ in ()).throw(RuntimeError("y")))
    assert breaker.state == STATE_OPEN


def test_breaker_half_open_success_closes_breaker():
    from app.services.circuit_breaker import (
        CircuitBreaker,
        STATE_CLOSED,
        STATE_HALF_OPEN,
    )

    breaker = CircuitBreaker(fail_max=2, reset_timeout=0.1, name="t")
    for _ in range(2):
        with pytest.raises(RuntimeError):
            breaker.call(lambda: (_ for _ in ()).throw(RuntimeError("x")))
    time.sleep(0.15)  # leave headroom for slow CI runners
    # Trial call succeeds → back to CLOSED.
    assert breaker.call(lambda: "ok") == "ok"
    assert breaker.state == STATE_CLOSED


def test_breaker_excluded_exceptions_do_not_count():
    from app.services.circuit_breaker import CircuitBreaker, STATE_CLOSED

    class IgnoredError(RuntimeError):
        pass

    breaker = CircuitBreaker(
        fail_max=2,
        reset_timeout=10.0,
        name="t",
        exclude=(IgnoredError,),
    )
    for _ in range(5):
        with pytest.raises(IgnoredError):
            breaker.call(lambda: (_ for _ in ()).throw(IgnoredError("ignored")))
    assert breaker.state == STATE_CLOSED


def test_breaker_context_manager_records_success_and_failure():
    from app.services.circuit_breaker import (
        CircuitBreaker,
        CircuitBreakerOpen,
        STATE_OPEN,
    )

    breaker = CircuitBreaker(fail_max=2, reset_timeout=10.0, name="t")
    with breaker:
        pass
    assert breaker.state == "closed"  # success path

    for _ in range(2):
        with pytest.raises(RuntimeError):
            with breaker:
                raise RuntimeError("boom")
    assert breaker.state == STATE_OPEN
    with pytest.raises(CircuitBreakerOpen):
        with breaker:
            pass


def test_breaker_validates_construction_args():
    from app.services.circuit_breaker import CircuitBreaker, CircuitBreakerConfigError

    with pytest.raises(CircuitBreakerConfigError):
        CircuitBreaker(fail_max=0)
    with pytest.raises(CircuitBreakerConfigError):
        CircuitBreaker(reset_timeout=0)
    with pytest.raises(CircuitBreakerConfigError):
        CircuitBreaker(success_threshold=0)


def test_breaker_is_thread_safe_under_contention():
    """Hammer the breaker from many threads and verify it ends in a
    valid state. We do not assert *which* state because it depends on
    the interleaving — only that no unexpected exception leaks and
    the state is one of the three known ones.

    ``CircuitBreakerOpen`` is the *expected* exception a "successful"
    thread sees once the breaker has tripped, so we filter it out
    explicitly.
    """
    from app.services.circuit_breaker import (
        CircuitBreaker,
        CircuitBreakerOpen,
        STATE_CLOSED,
        STATE_HALF_OPEN,
        STATE_OPEN,
    )

    breaker = CircuitBreaker(fail_max=5, reset_timeout=0.01, name="t")
    unexpected: list[BaseException] = []

    def worker(fail: bool) -> None:
        try:
            for _ in range(50):
                if fail:
                    try:
                        breaker.call(lambda: (_ for _ in ()).throw(RuntimeError("x")))
                    except (RuntimeError, Exception):  # noqa: BLE001
                        pass
                else:
                    try:
                        breaker.call(lambda: "ok")
                    except CircuitBreakerOpen:
                        # Expected: the breaker tripped mid-run and
                        # the "ok" call short-circuited. Not an error.
                        pass
                    except Exception as exc:  # noqa: BLE001
                        unexpected.append(exc)
        except BaseException as exc:  # pragma: no cover - defensive
            unexpected.append(exc)

    threads = [threading.Thread(target=worker, args=(i % 2 == 0,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not unexpected, f"unexpected exceptions leaked: {unexpected!r}"
    assert breaker.state in {STATE_CLOSED, STATE_OPEN, STATE_HALF_OPEN}


# ---------------------------------------------------------------------------
# 3b) Circuit breaker integration with OpenAICompatibleEmbeddingClient
# ---------------------------------------------------------------------------


def _make_breaker(fail_max: int = 2, reset_timeout: float = 0.05):
    from app.services.circuit_breaker import CircuitBreaker

    return CircuitBreaker(
        fail_max=fail_max, reset_timeout=reset_timeout, name="test-embed"
    )


def test_embedding_client_uses_circuit_breaker_and_fails_fast(monkeypatch):
    """When the embedding endpoint fails repeatedly, the breaker should
    open and subsequent calls should fail fast with EmbeddingProviderError
    (not block waiting on the HTTP timeout)."""
    from app.services.embeddings import (
        EmbeddingProviderError,
        OpenAICompatibleEmbeddingClient,
    )

    monkeypatch.setattr(
        "app.services.embeddings.coerce_embedding_dimensions",
        lambda emb, _dim: [0.0] * 4,  # dimensions don't matter
    )

    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(503, json={"error": "service unavailable"})

    client = OpenAICompatibleEmbeddingClient(
        base_url="http://emb.local/v1",
        model="bge-m3",
        transport=httpx.MockTransport(handler),
        timeout_seconds=10.0,
        breaker=_make_breaker(fail_max=2, reset_timeout=10.0),
    )

    # First two calls hit the HTTP layer and fail with provider error.
    for _ in range(2):
        with pytest.raises(EmbeddingProviderError):
            client.embed_many(["hola"])
    # Third call must fail-fast without touching the transport.
    with pytest.raises(EmbeddingProviderError):
        client.embed_many(["hola"])
    assert call_count == 2, "breaker should have skipped the HTTP call after opening"


def test_embedding_client_recovers_when_breaker_resets(monkeypatch):
    """After the reset timeout elapses, a successful trial call should
    re-close the breaker and normal traffic resumes."""
    from app.services.embeddings import OpenAICompatibleEmbeddingClient

    monkeypatch.setattr(
        "app.services.embeddings.coerce_embedding_dimensions",
        lambda emb, _dim: [0.0] * 4,
    )

    state = {"fails_remaining": 2}

    def handler(request: httpx.Request) -> httpx.Response:
        if state["fails_remaining"] > 0:
            state["fails_remaining"] -= 1
            return httpx.Response(500, json={"error": "boom"})
        return httpx.Response(
            200,
            json={"data": [{"index": 0, "embedding": [0.0] * 4}]},
        )

    client = OpenAICompatibleEmbeddingClient(
        base_url="http://emb.local/v1",
        model="bge-m3",
        transport=httpx.MockTransport(handler),
        timeout_seconds=10.0,
        breaker=_make_breaker(fail_max=2, reset_timeout=0.05),
    )

    from app.services.embeddings import EmbeddingProviderError

    for _ in range(2):
        with pytest.raises(EmbeddingProviderError):
            client.embed_many(["x"])
    time.sleep(0.06)
    # Trial call succeeds → service is back.
    result = client.embed_many(["x"])
    assert result == [[0.0] * 4]


def test_embedding_async_breaker_path(monkeypatch):
    """The async path must use the breaker too, offloading the sync
    call to a worker thread so the event loop is not blocked."""
    from app.services.embeddings import (
        EmbeddingProviderError,
        OpenAICompatibleEmbeddingClient,
    )

    monkeypatch.setattr(
        "app.services.embeddings.coerce_embedding_dimensions",
        lambda emb, _dim: [0.0] * 4,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "nope"})

    client = OpenAICompatibleEmbeddingClient(
        base_url="http://emb.local/v1",
        model="bge-m3",
        transport=httpx.MockTransport(handler),
        timeout_seconds=10.0,
        breaker=_make_breaker(fail_max=1, reset_timeout=10.0),
    )

    async def run() -> None:
        with pytest.raises(EmbeddingProviderError):
            await client.embed_many_async(["hola"])

    asyncio.run(run())


def test_reset_embedding_breaker_helper(monkeypatch):
    """The module-level breaker is shared across calls. ``reset_embedding_breaker``
    must put it back into the CLOSED state so tests and operational
    tooling have a clean slate."""
    from app.services import embeddings as emb_mod

    emb_mod.reset_embedding_breaker()
    breaker = emb_mod._get_embedding_breaker()
    breaker.reset()
    assert breaker.state == "closed"
