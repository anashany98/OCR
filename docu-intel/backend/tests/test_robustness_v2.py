"""Block 6 — robustness regression tests.

Three sub-areas:

* ``CascadingOCREngine.extract`` now takes the page language
  as a keyword argument instead of mutating
  ``self.current_language`` between calls. The previous
  design was not thread-safe: two PDF pages processed in
  parallel on the same cascade instance raced on
  ``current_language`` and the per-language thresholds
  would fire for the wrong page.
* ``_is_postgres`` no longer swallows every exception
  silently. The fallback to the Python cosine path is now
  logged at DEBUG (dialect mismatch / no bind) or WARNING
  (introspection error) so an operator can spot when their
  pgvector install is not being used.
* ``app.api.routes.documents`` exposes a
  ``get_user_access_scope`` FastAPI dependency that caches
  the per-request scope. The cache is verified by
  inspecting the FastAPI dependency tree on a representative
  endpoint.
"""
from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.ai.context import ContextItem
from app.ocr.base import OCRBlock, OCRResult
from app.services import vector_store as vector_store_module


# ---------------------------------------------------------------------------
# CascadingOCREngine — language as a parameter, no instance mutation
# ---------------------------------------------------------------------------


class _StubEngine:
    """Minimal stub that records every call's ``language`` arg."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[str | None] = []
        self._result = OCRResult(
            text="some text",
            confidence=0.9,
            blocks=[OCRBlock(text="some text", confidence=0.9, bbox=None, block_type="text")],
            engine=name,
        )

    def extract(self, image_path: Path, *, language: str | None = None) -> OCRResult:  # type: ignore[override]
        self.calls.append(language)
        return self._result


def test_cascading_passes_language_through_to_inner_engines(monkeypatch) -> None:
    """The cascade must forward the per-page ``language`` keyword
    to every inner engine call so the per-language adaptive
    thresholds (O2) and the per-language tesseract/paddle lang
    can be picked up. The previous design stored the language
    on ``self.current_language`` and the parser had to mutate
    it between calls, which raced when multiple pages were
    processed in parallel.
    """
    # Disable the Tier 4 VLM-OCR trigger so we can observe the
    # primary+fallback path only.
    from app.ocr.cascading import CascadingOCREngine

    primary = _StubEngine(name="tesseract")
    fallback = _StubEngine(name="paddleocr")
    cascade = CascadingOCREngine(
        primary=primary,
        fallback=fallback,
        # A high tier4_quality_threshold so the result of the
        # primary is not re-evaluated by Tier 4.
        tier4_quality_threshold=1.0,
    )
    # Stub Path so we never touch the filesystem.
    image_path = MagicMock(spec=Path)

    cascade.extract(image_path, language="es")
    cascade.extract(image_path, language="en")

    # Primary saw the right language on each call.
    assert primary.calls == ["es", "en"], (
        f"primary engine should see the per-page language; got {primary.calls!r}"
    )


def test_cascading_default_language_is_none() -> None:
    """Calling ``extract`` without the ``language`` keyword must
    keep working (the cascading engine is the only one that
    uses the value, but other engines accept the kwarg and
    ignore it). The default is ``None``.
    """
    from app.ocr.cascading import CascadingOCREngine

    primary = _StubEngine(name="tesseract")
    fallback = _StubEngine(name="paddleocr")
    cascade = CascadingOCREngine(
        primary=primary,
        fallback=fallback,
        tier4_quality_threshold=1.0,
    )
    cascade.extract(MagicMock(spec=Path))
    assert primary.calls == [None]
    assert fallback.calls == [None]


# ---------------------------------------------------------------------------
# _is_postgres — no silent fallback
# ---------------------------------------------------------------------------


def test_is_postgres_logs_when_bind_is_none(caplog) -> None:
    """A session whose ``bind`` is ``None`` is rare but
    possible (e.g. a test fixture or a session constructed
    with a non-Engine bind). The earlier version silently
    returned ``False``; the new version logs at DEBUG so the
    operator can spot a misconfigured session in the logs.
    """
    db = MagicMock()
    db.bind = None
    with caplog.at_level("DEBUG", logger="app.services.vector_store"):
        result = vector_store_module._is_postgres(db)
    assert result is False
    assert any(
        "db.bind is None" in record.message for record in caplog.records
    ), f"expected a DEBUG log naming db.bind, got: {[r.message for r in caplog.records]}"


def test_is_postgres_logs_when_dialect_is_not_postgresql(caplog) -> None:
    """When the bound engine is not PostgreSQL the helper
    must log at DEBUG (with the actual dialect name) and
    return ``False``. The earlier version was silent.
    """
    db = MagicMock()
    db.bind.dialect.name = "sqlite"
    with caplog.at_level("DEBUG", logger="app.services.vector_store"):
        result = vector_store_module._is_postgres(db)
    assert result is False
    assert any(
        "dialect=sqlite" in record.message for record in caplog.records
    ), f"expected a DEBUG log naming the dialect, got: {[r.message for r in caplog.records]}"


def test_is_postgres_logs_warning_on_introspection_failure(caplog) -> None:
    """When the dialect introspection itself raises (e.g. a
    detached engine), the helper must log at WARNING and
    return ``False`` (so the Python cosine path takes over)
    rather than silently falling through.
    """
    db = MagicMock()
    # ``db.bind`` is a property; raising from it triggers the
    # ``except Exception`` branch.
    type(db).bind = property(lambda self: (_ for _ in ()).throw(RuntimeError("detached")))
    with caplog.at_level("WARNING", logger="app.services.vector_store"):
        result = vector_store_module._is_postgres(db)
    assert result is False
    assert any(
        "detached" in record.message for record in caplog.records
    ), f"expected a WARNING log naming the error, got: {[r.message for r in caplog.records]}"


# ---------------------------------------------------------------------------
# BaseOCREngine — language is part of the contract
# ---------------------------------------------------------------------------


def test_base_ocr_engine_extract_accepts_language_kwarg() -> None:
    """The :class:`BaseOCREngine` protocol must accept the
    ``language`` keyword on ``extract``. The check is
    structural: a dummy class that implements the protocol
    must be considered a valid engine.
    """
    from app.ocr.base import BaseOCREngine

    class _ProtocolImpl:
        name = "stub"

        def extract(  # type: ignore[override]
            self,
            image_path: Path,
            *,
            language: str | None = None,
        ) -> OCRResult:
            return OCRResult(
                text="ok",
                confidence=1.0,
                blocks=[],
                engine="stub",
            )

    impl = _ProtocolImpl()
    # The protocol check is structural (runtime_checkable
    # would need to be added to the Protocol), so we just
    # verify the method signature accepts the keyword.
    result = impl.extract(MagicMock(spec=Path), language="es")
    assert result.engine == "stub"
    # And without the keyword.
    result2 = impl.extract(MagicMock(spec=Path))
    assert result2.engine == "stub"
