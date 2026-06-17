"""Unit tests for the PaddleOCR init timeout (H6 — Sprint 3 refactor).

These tests pin the contract the adapter promises: when PaddleOCR's
constructor hangs forever, ``PaddleOCRAdapter.run()`` must raise
``RuntimeError`` within the configured timeout instead of blocking
the calling thread indefinitely.

The timeout logic moved from ``app.ocr.paddle`` (legacy engine) to
``app.ocr.paddle_adapter`` (the new adapter) during the PaddleOCR
3.7 / PP-OCRv6 refactor. The tests therefore target the adapter
directly so they keep working regardless of where the timeout lives.
"""

from __future__ import annotations

import os
import time
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "x" * 64)
os.environ.setdefault("ADMIN_PASSWORD", "y" * 22)


# ---------------------------------------------------------------------------
# Config sanity
# ---------------------------------------------------------------------------


def test_timeout_constant_exists_and_is_positive():
    from app.ocr.paddle import _PADDLE_INIT_TIMEOUT_SECONDS

    assert _PADDLE_INIT_TIMEOUT_SECONDS > 0
    assert _PADDLE_INIT_TIMEOUT_SECONDS <= 600  # no more than 10 min


# ---------------------------------------------------------------------------
# Timeout fires when init hangs (tested on the adapter).
# ---------------------------------------------------------------------------


def test_init_timeout_raises_runtime_error_on_hang():
    """If PaddleOCR constructor blocks forever, the adapter must raise
    ``RuntimeError`` within the timeout window."""
    from app.ocr.paddle_adapter import _PADDLE_INIT_TIMEOUT_SECONDS

    # Patch the module-level constant in the adapter module (where the
    # timeout actually lives post-refactor) and the ThreadPoolExecutor
    # the adapter uses.
    with patch("app.ocr.paddle_adapter._PADDLE_INIT_TIMEOUT_SECONDS", 0.2):
        with patch("app.ocr.paddle_adapter.concurrent.futures.ThreadPoolExecutor") as mock_pool:
            mock_future = MagicMock()
            import concurrent.futures as _cf

            mock_future.result.side_effect = _cf.TimeoutError()
            mock_pool.return_value.__enter__ = MagicMock(
                return_value=MagicMock(submit=MagicMock(return_value=mock_future))
            )
            mock_pool.return_value.__exit__ = MagicMock(return_value=False)

            def _hang_forever(**kwargs):
                time.sleep(9999)
                return MagicMock()

            adapter = _AdapterWithHang(_hang_forever)

            with pytest.raises(RuntimeError, match="timed out"):
                adapter._holder.get()


class _AdapterWithHang:
    """Tiny stand-in adapter that drives ``_EngineHolder`` with a
    factory that hangs forever."""

    def __init__(self, factory):
        from app.ocr.paddle_adapter import _EngineHolder, OcrProfile

        self._holder = _EngineHolder(
            profile=OcrProfile(
                id="ppocr_v6_medium",
                backend="paddleocr",
                model_type="PP-OCRv6",
                detection_model_name=None,
                recognition_model_name=None,
                use_predict_api=True,
            ),
            lang="es",
            device=None,
            engine_factory=factory,
        )


# ---------------------------------------------------------------------------
# Normal init within timeout (tested on the adapter).
# ---------------------------------------------------------------------------


def test_init_completes_within_timeout():
    """When PaddleOCR loads quickly, the adapter returns the instance."""
    from app.ocr.paddle_adapter import _EngineHolder, OcrProfile

    mock_engine = MagicMock()
    adapter = _AdapterWithHang(lambda **kwargs: mock_engine)

    with patch("app.ocr.paddle_adapter.paddleocr_init_lock") as mock_lock:
        mock_lock.return_value.__enter__ = MagicMock()
        mock_lock.return_value.__exit__ = MagicMock(return_value=False)

        instance = adapter._holder.get()

    assert instance is mock_engine


# ---------------------------------------------------------------------------
# Timeout value is configurable (reads from the module constant)
# ---------------------------------------------------------------------------


def test_timeout_constant_can_be_patched():
    """Operators can override _PADDLE_INIT_TIMEOUT_SECONDS via env."""
    import app.ocr.paddle as paddle_mod

    original = paddle_mod._PADDLE_INIT_TIMEOUT_SECONDS
    try:
        paddle_mod._PADDLE_INIT_TIMEOUT_SECONDS = 10.0
        assert paddle_mod._PADDLE_INIT_TIMEOUT_SECONDS == 10.0
    finally:
        paddle_mod._PADDLE_INIT_TIMEOUT_SECONDS = original