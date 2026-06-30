"""
Unit tests for OCR-INIT-1 (Sprint 2).

Verifies that:

1. The new ``track_worker_init_failure`` metric is exposed and
   buckets unknown stage values to ``"other"``.
2. The preload hook in ``app.workers.celery_app`` emits the
   metric and logs the stack trace when the engine fails to
   preload.
3. ``_exercise`` (the synthetic image warmup) is best-effort:
   any failure is swallowed so the worker still boots.
4. ``preload_ocr_engine`` runs both warmup and exercise.

We mock the heavy dependencies (Paddle, Tesseract) to keep the
tests fast and runnable on any machine.
"""
from __future__ import annotations

import logging
import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "x" * 64)
os.environ.setdefault("ADMIN_PASSWORD", "y" * 22)


# ---------------------------------------------------------------------------
# Metric
# ---------------------------------------------------------------------------


class TestTrackWorkerInitFailure:
    """The metric buckets unknown stage values to ``"other"``."""

    def test_increments_with_known_stage(self):
        from app.services.metrics import track_worker_init_failure
        from app.services.metrics._registry import WORKER_INIT_FAILURES

        before = WORKER_INIT_FAILURES.labels(stage="ocr_preload")._value.get()
        track_worker_init_failure("ocr_preload")
        after = WORKER_INIT_FAILURES.labels(stage="ocr_preload")._value.get()
        assert after == before + 1

    def test_increments_with_unknown_stage_to_other(self):
        from app.services.metrics import track_worker_init_failure
        from app.services.metrics._registry import WORKER_INIT_FAILURES

        before = WORKER_INIT_FAILURES.labels(stage="other")._value.get()
        track_worker_init_failure("totally_bogus_stage_name")
        after = WORKER_INIT_FAILURES.labels(stage="other")._value.get()
        assert after == before + 1

    def test_increments_count(self):
        from app.services.metrics import track_worker_init_failure
        from app.services.metrics._registry import WORKER_INIT_FAILURES

        before = WORKER_INIT_FAILURES.labels(stage="ocr_preload")._value.get()
        track_worker_init_failure("ocr_preload", count=3)
        after = WORKER_INIT_FAILURES.labels(stage="ocr_preload")._value.get()
        assert after == before + 3

    def test_zero_count_is_noop(self):
        from app.services.metrics import track_worker_init_failure
        from app.services.metrics._registry import WORKER_INIT_FAILURES

        before_ocr = WORKER_INIT_FAILURES.labels(stage="ocr_preload")._value.get()
        before_other = WORKER_INIT_FAILURES.labels(stage="other")._value.get()
        track_worker_init_failure("ocr_preload", count=0)
        after_ocr = WORKER_INIT_FAILURES.labels(stage="ocr_preload")._value.get()
        after_other = WORKER_INIT_FAILURES.labels(stage="other")._value.get()
        assert after_ocr == before_ocr
        assert after_other == before_other


# ---------------------------------------------------------------------------
# Celery init hook
# ---------------------------------------------------------------------------


class TestPreloadWorkerOcrEngine:
    """The ``worker_process_init`` hook must:

    * log a full stack trace (not just a string) on failure
    * emit ``track_worker_init_failure(stage="ocr_preload")``
    """

    def test_success_does_not_emit_failure_metric(self, monkeypatch):
        """Patch at the SOURCE because the hook does a local
        ``from app.ocr.factory import preload_ocr_engine``."""
        from app.workers import celery_app as celery_app_module

        monkeypatch.setenv("WORKER_NAME", "worker-heavy")
        with patch("app.services.metrics.track_worker_init_failure") as mock_metric:
            with patch("app.ocr.factory.preload_ocr_engine", return_value=MagicMock()):
                celery_app_module.preload_worker_ocr_engine()
            mock_metric.assert_not_called()

    def test_failure_emits_metric_and_logs_stack_trace(self, caplog, monkeypatch):
        from app.workers import celery_app as celery_app_module

        monkeypatch.setenv("WORKER_NAME", "worker-heavy")
        with patch("app.services.metrics.track_worker_init_failure") as mock_metric:
            with patch(
                "app.ocr.factory.preload_ocr_engine",
                side_effect=RuntimeError("Paddle not installed"),
            ):
                with caplog.at_level(
                    logging.ERROR, logger="app.workers.celery_app"
                ):
                    celery_app_module.preload_worker_ocr_engine()
            # Metric was emitted with the right stage.
            mock_metric.assert_called_once_with(stage="ocr_preload")
            # The log message names the hook.
            assert any(
                "OCR engine preload failed during worker init" in record.message
                for record in caplog.records
            ), f"missing log message; got: {[r.message for r in caplog.records]}"
            # And it carries an exception (the stack trace is
            # attached by logger.exception).
            assert any(
                record.exc_info is not None for record in caplog.records
            ), "logger.exception should attach a stack trace"

    def test_skips_non_ocr_worker(self, monkeypatch, caplog):
        from app.workers import celery_app as celery_app_module

        monkeypatch.setenv("WORKER_NAME", "worker-fast")
        with patch("app.ocr.factory.preload_ocr_engine") as mock_preload:
            with caplog.at_level(logging.INFO, logger="app.workers.celery_app"):
                celery_app_module.preload_worker_ocr_engine()

        mock_preload.assert_not_called()
        assert any("ocr_preload_skipped" in record.message for record in caplog.records)

    def test_metric_failure_does_not_break_worker(self, monkeypatch):
        """If the metric emission itself fails (e.g. the metrics
        module is broken), the worker must still come up.
        """
        from app.workers import celery_app as celery_app_module

        monkeypatch.setenv("WORKER_NAME", "worker-heavy")
        with patch(
            "app.ocr.factory.preload_ocr_engine",
            side_effect=RuntimeError("Paddle not installed"),
        ):
            with patch(
                "app.services.metrics.track_worker_init_failure",
                side_effect=Exception("metrics broken"),
            ):
                # The hook must not raise.
                celery_app_module.preload_worker_ocr_engine()


# ---------------------------------------------------------------------------
# _exercise()
# ---------------------------------------------------------------------------


class TestExercise:
    """``_exercise`` runs a synthetic extraction. Best-effort."""

    def test_exercise_swallows_engine_failure(self):
        from app.ocr import factory as factory_module

        engine = MagicMock()
        engine.name = "fake"
        engine.extract.side_effect = RuntimeError("compile fail")
        # The function must NOT raise.
        factory_module._exercise(engine)

    def test_exercise_swallows_missing_opencv(self, monkeypatch):
        """If opencv is not installed, the exercise is a no-op."""
        from app.ocr import factory as factory_module

        # Simulate ImportError on the lazy cv2 import.
        import builtins
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name in ("cv2", "numpy"):
                raise ImportError(f"no {name}")
            return original_import(name, *args, **kwargs)

        engine = MagicMock()
        engine.name = "fake"
        monkeypatch.setattr(builtins, "__import__", mock_import)
        # Must not raise.
        factory_module._exercise(engine)
        # Engine.extract was NOT called because the import failed
        # before the engine call.
        engine.extract.assert_not_called()

    def test_exercise_runs_extract_on_synthetic_image(self, monkeypatch):
        """When the import succeeds, the engine is exercised and
        the synthetic image is cleaned up.
        """
        from app.ocr import factory as factory_module
        from app.core.config import settings

        # Set files_dir to a real path so the exercise can run.
        # (The function doesn't actually use files_dir but the
        # presence check requires it.)
        monkeypatch.setattr(settings, "files_dir", "/tmp")

        engine = MagicMock()
        engine.name = "fake"
        engine.extract.return_value = MagicMock(text="ok", confidence=0.5)
        factory_module._exercise(engine)
        engine.extract.assert_called_once()
        # The extract was called with a Path.
        call_arg = engine.extract.call_args[0][0]
        assert hasattr(call_arg, "exists") or isinstance(call_arg, str)


# ---------------------------------------------------------------------------
# preload_ocr_engine()
# ---------------------------------------------------------------------------


class TestPreloadOcrEngine:
    """``preload_ocr_engine`` runs both warmup and exercise."""

    def test_runs_warmup_and_exercise(self, monkeypatch):
        from app.ocr import factory as factory_module

        # Stub the engine builder + warmup + exercise.
        fake_engine = MagicMock()
        fake_engine.name = "fake"

        with patch.object(
            factory_module, "get_ocr_engine", return_value=fake_engine
        ) as mock_get:
            with patch.object(factory_module, "_warm_ocr_engine") as mock_warm:
                with patch.object(factory_module, "_exercise") as mock_exercise:
                    result = factory_module.preload_ocr_engine()
        assert result is fake_engine
        mock_get.assert_called_once()
        mock_warm.assert_called_once_with(fake_engine)
        mock_exercise.assert_called_once_with(fake_engine)
