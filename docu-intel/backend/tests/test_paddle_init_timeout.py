"""
Unit tests for O6: PaddleOCR model init must not leave orphan threads.

The OCR worker preloads models in ``worker_process_init``. PaddleOCR
must therefore initialise in the worker's own thread/process instead of
spawning a helper thread and waiting with a timeout: if the helper gets
stuck in CUDA/model loading, Python cannot cancel it and VRAM keeps
growing in the background.
"""
from __future__ import annotations

import os
import threading
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "x" * 64)
os.environ.setdefault("ADMIN_PASSWORD", "y" * 22)


# ---------------------------------------------------------------------------
# Init runs synchronously in the worker process
# ---------------------------------------------------------------------------


def test_init_runs_in_calling_thread_without_executor():
    """PaddleOCR construction happens in the current thread.

    This is the regression guard for O6. The old implementation used a
    ``ThreadPoolExecutor`` plus ``future.result(timeout=...)``; when the
    constructor timed out the background thread kept loading the model.
    """
    from app.ocr.paddle import PaddleOCREngine

    calling_thread = threading.get_ident()
    seen_threads: list[int] = []
    mock_engine = MagicMock()

    def _build_engine(**_kwargs):
        seen_threads.append(threading.get_ident())
        return mock_engine

    mock_paddle_module = MagicMock()
    mock_paddle_module.PaddleOCR = MagicMock(side_effect=_build_engine)
    engine = PaddleOCREngine(lang="es", device=None)

    with patch.dict("sys.modules", {"paddleocr": mock_paddle_module}):
        with patch("app.ocr.paddle.paddleocr_init_lock") as mock_lock:
            mock_lock.return_value.__enter__ = MagicMock()
            mock_lock.return_value.__exit__ = MagicMock(return_value=False)
            result = engine._init_engine_with_timeout()

    assert result is mock_engine
    assert seen_threads == [calling_thread]


# ---------------------------------------------------------------------------
# Normal init within timeout
# ---------------------------------------------------------------------------


def test_init_completes_within_timeout():
    """When PaddleOCR loads, the engine returns the instance."""
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
# Init failures are sticky
# ---------------------------------------------------------------------------


def test_init_failure_marks_engine_unavailable():
    """After an init failure, subsequent access raises a clear error
    without retrying model construction in a loop."""
    from app.ocr.paddle import PaddleOCREngine

    mock_paddle_class = MagicMock(side_effect=RuntimeError("model download failed"))
    mock_paddle_module = MagicMock()
    mock_paddle_module.PaddleOCR = mock_paddle_class
    engine = PaddleOCREngine(lang="es", device=None)

    with patch.dict("sys.modules", {"paddleocr": mock_paddle_module}):
        with patch("app.ocr.paddle.paddleocr_init_lock") as mock_lock:
            mock_lock.return_value.__enter__ = MagicMock()
            mock_lock.return_value.__exit__ = MagicMock(return_value=False)
            with pytest.raises(RuntimeError, match="PaddleOCR engine unavailable"):
                engine._init_engine_with_timeout()
            with pytest.raises(RuntimeError, match="PaddleOCR engine unavailable"):
                engine._init_engine_with_timeout()

    mock_paddle_class.assert_called_once()
