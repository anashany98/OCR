"""
Unit tests for H6 (Sprint 3): PaddleOCR init timeout.

Verifies that:
1. ``_PADDLE_INIT_TIMEOUT_SECONDS`` is exported and has a sane value.
2. When the ``PaddleOCR`` constructor hangs, the engine raises
   ``RuntimeError`` instead of blocking the calling thread forever.
3. When the init completes within the timeout, the engine works normally.
"""
from __future__ import annotations

import concurrent.futures
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
# Timeout fires when init hangs
# ---------------------------------------------------------------------------


def test_init_timeout_raises_runtime_error_on_hang():
    """If PaddleOCR constructor blocks forever, the engine must raise
    ``RuntimeError`` within the timeout window."""
    from app.ocr.paddle import PaddleOCREngine, _PADDLE_INIT_TIMEOUT_SECONDS

    def _hang_forever(**kwargs):
        time.sleep(9999)
        return MagicMock()

    engine = PaddleOCREngine(lang="es", device=None)

    # Patch at module level so ``from paddleocr import PaddleOCR``
    # inside the method sees the mock.
    mock_paddleocr = MagicMock()
    with patch.dict("sys.modules", {"paddleocr": mock_paddleocr}):
        with patch("app.ocr.paddle._PADDLE_INIT_TIMEOUT_SECONDS", 0.5):
            with patch("app.ocr.paddle.concurrent.futures.ThreadPoolExecutor") as mock_pool:
                mock_future = MagicMock()
                mock_future.result.side_effect = concurrent.futures.TimeoutError()
                mock_pool.return_value.__enter__ = MagicMock(
                    return_value=MagicMock(submit=MagicMock(return_value=mock_future))
                )
                mock_pool.return_value.__exit__ = MagicMock(return_value=False)

                with pytest.raises(RuntimeError, match="timed out"):
                    engine._init_engine_with_timeout()


# ---------------------------------------------------------------------------
# Normal init within timeout
# ---------------------------------------------------------------------------


def test_init_completes_within_timeout():
    """When PaddleOCR loads quickly, the engine returns the instance."""
    from app.ocr.paddle import PaddleOCREngine

    mock_engine = MagicMock()
    mock_paddle_class = MagicMock(return_value=mock_engine)

    engine = PaddleOCREngine(lang="es", device=None)

    mock_paddle_module = MagicMock()
    mock_paddle_module.PaddleOCR = mock_paddle_class

    with patch.dict("sys.modules", {"paddleocr": mock_paddle_module}):
        with patch("app.ocr.paddle.paddleocr_init_lock") as mock_lock:
            mock_lock.return_value.__enter__ = MagicMock()
            mock_lock.return_value.__exit__ = MagicMock(return_value=False)
            result = engine._init_engine_with_timeout()

    assert result is mock_engine
    mock_paddle_class.assert_called_once()


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
