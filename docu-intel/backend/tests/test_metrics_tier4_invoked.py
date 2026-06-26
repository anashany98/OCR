"""
Tests for M1 (track_ocr_tier4_invoked) and M2 (warmup GPU/CUDA WARNING).

These changes add observability hooks that were missing from the OCR
cascade:

* M1: every time the cascade consults Tier 4 (VLM) the reason is
  counted in ``docuintel_ocr_tier4_invoked_total{reason=...}`` so
  the operator can distinguish "the rest of the cascade is weak"
  from "the breaker is open" in Grafana.
* M2: if any sub-engine was built with a GPU device string but
  ``torch.cuda.is_available()`` is False, the worker logs a single
  WARNING at preload so a CPU-only container booted with
  ``PADDLE_DEVICE=gpu`` doesn't silently fall back to CPU on the
  first real job.
"""
from __future__ import annotations

import logging
import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "x" * 64)
os.environ.setdefault("ADMIN_PASSWORD", "y" * 22)

import pytest

from app.services.metrics import track_ocr_tier4_invoked
from app.services.metrics._registry import OCR_TIER4_INVOKED


# ---------------------------------------------------------------------------
# M1: track_ocr_tier4_invoked
# ---------------------------------------------------------------------------


def _read_tier4_count(reason: str) -> float:
    """Return the current value of the Tier 4 invoked counter for a reason."""
    return OCR_TIER4_INVOKED.labels(reason=reason)._value.get()  # noqa: SLF001


@pytest.mark.parametrize("reason", ["under_threshold", "circuit_open", "explicit_call"])
def test_track_ocr_tier4_invoked_increments_known_reasons(reason):
    before = _read_tier4_count(reason)
    track_ocr_tier4_invoked(reason)
    assert _read_tier4_count(reason) == before + 1


def test_track_ocr_tier4_invoked_buckets_unknown_reason_to_other():
    """An unknown reason must not blow up the Prometheus cardinality;
    it buckets to ``"other"`` so the time series stays bounded.
    """
    before = _read_tier4_count("other")
    track_ocr_tier4_invoked("some_unmapped_reason")
    after = _read_tier4_count("other")
    assert after == before + 1
    # Sanity: the implementation uses ``OCR_TIER4_INVOKED.labels(reason=clean)``
    # so an unmapped reason never reaches the registry with that label —
    # which is the whole point of the bucketing. We can't easily observe
    # the absence of a label without touching the global registry, so
    # the assertion above (other went up by 1) is the observable
    # contract. The fact that the unknown label never grows beyond its
    # default-zero initial value is a property of the implementation.


def test_track_ocr_tier4_invoked_normalises_case_and_whitespace():
    """The reason is lowercased + trimmed before the label lookup so
    callers don't accidentally create a new time series."""
    before = _read_tier4_count("under_threshold")
    track_ocr_tier4_invoked("  UNDER_THRESHOLD  ")
    assert _read_tier4_count("under_threshold") == before + 1


def test_track_ocr_tier4_invoked_handles_none_and_empty():
    """``None`` and empty strings are bucketed to ``"other"`` instead
    of raising."""
    before = _read_tier4_count("other")
    track_ocr_tier4_invoked(None)
    track_ocr_tier4_invoked("")
    assert _read_tier4_count("other") == before + 2


# ---------------------------------------------------------------------------
# M2: factory._warn_if_gpu_requested_but_unavailable
# ---------------------------------------------------------------------------


def _make_stub_engine(*, device: str | None, name: str = "stub") -> object:
    """Minimal stand-in for an OCR engine carrying a ``device`` attribute."""

    class _Stub:
        pass

    stub = _Stub()
    stub.name = name
    stub.device = device
    return stub


def test_warn_if_gpu_requested_but_unavailable_logs_when_no_cuda(monkeypatch, caplog):
    """M2: a worker that requests ``device='gpu:0'`` but runs on a
    CPU-only container must log a WARNING so the operator notices
    the misconfiguration.
    """
    import torch

    from app.ocr import factory

    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)

    engine = _make_stub_engine(device="gpu:0", name="paddleocr")
    with caplog.at_level(logging.WARNING, logger="app.ocr.factory"):
        factory._warn_if_gpu_requested_but_unavailable(engine)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings, "expected at least one WARNING"
    assert any("gpu:0" in r.getMessage() for r in warnings)
    assert any("torch.cuda.is_available" in r.getMessage() for r in warnings)


def test_warn_if_gpu_requested_but_unavailable_no_warning_when_cuda_ok(monkeypatch, caplog):
    """M2: when CUDA IS available there is no WARNING — the engine
    is correctly configured."""
    import torch

    from app.ocr import factory

    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)

    engine = _make_stub_engine(device="gpu:0", name="paddleocr")
    with caplog.at_level(logging.WARNING, logger="app.ocr.factory"):
        factory._warn_if_gpu_requested_but_unavailable(engine)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings == []


def test_warn_if_gpu_requested_but_unavailable_no_warning_for_cpu_device(monkeypatch, caplog):
    """M2: a CPU-only engine (``device='cpu'`` or ``None``) must NOT
    trigger the WARNING even on a CUDA-less host — that's the
    legitimate config for CPU workers.
    """
    import torch

    from app.ocr import factory

    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)

    for cpu_device in (None, "cpu"):
        engine = _make_stub_engine(device=cpu_device, name="paddleocr")
        with caplog.at_level(logging.WARNING, logger="app.ocr.factory"):
            factory._warn_if_gpu_requested_but_unavailable(engine)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings == []


def test_warn_if_gpu_requested_but_unavailable_silent_without_torch(monkeypatch, caplog):
    """M2: if torch isn't installed at all (a CPU-only image that
    doesn't need it) we don't have a way to check CUDA; stay silent
    rather than spam the logs.
    """
    from app.ocr import factory

    # Simulate ``torch`` not present by hiding it from the
    # ``import torch`` statement inside the function. ``factory``
    # does the import lazily so we just need to make the name
    # unresolvable for the duration of the call.
    import builtins

    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "torch":
            raise ImportError("simulated: torch not installed")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    engine = _make_stub_engine(device="gpu:0", name="paddleocr")
    with caplog.at_level(logging.WARNING, logger="app.ocr.factory"):
        factory._warn_if_gpu_requested_but_unavailable(engine)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings == []


def test_warn_if_gpu_requested_but_unavailable_walks_cascade_tree(monkeypatch, caplog):
    """M2: a ``CascadingOCREngine`` with a GPU ``fallback`` (Paddle)
    and a CPU primary (Tesseract) must still WARN if CUDA isn't
    available — the operator needs to know the GPU tier is
    degraded.
    """
    import torch

    from app.ocr import factory

    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)

    primary = _make_stub_engine(device="cpu", name="tesseract")
    fallback = _make_stub_engine(device="gpu:0", name="paddleocr")

    class _Cascade:
        name = "cascading"

    cascade = _Cascade()
    cascade.fallback = fallback
    cascade.primary = primary

    with caplog.at_level(logging.WARNING, logger="app.ocr.factory"):
        factory._warn_if_gpu_requested_but_unavailable(cascade)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("gpu:0" in r.getMessage() for r in warnings)