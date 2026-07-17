"""Regression test for the handwritten-routing fix (2026-07-16).

When ``classify_content`` flags a page as ``vlm_ocr`` (because the
filename declares a handwritten document type), the cascade must
skip the primary OCR engines and go straight to the VLM tier.
Without this, the empty body from Tesseract/Paddle would pass the
``_is_acceptable`` gate as if it were legitimate.
"""
from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock


def _make_cascade(vlm=None) -> "CascadingOCREngine":  # noqa: F821
    from app.ocr.cascading import CascadingOCREngine

    engine = CascadingOCREngine.__new__(CascadingOCREngine)
    engine._tls = threading.local()
    engine._tls.content_route = None
    engine._tls.document_id = None
    engine._tls.page_number = None
    engine.vlm_ocr = vlm
    if vlm is not None:
        vlm.should_force_tier4 = MagicMock(return_value=False)
    return engine


def test_vlm_route_forces_tier4():
    """content_route=vlm_ocr must short-circuit _should_force_tier4 to True."""
    from app.parsers.content_router import ContentRoute

    engine = _make_cascade(vlm=MagicMock(name="vlm_ocr"))
    engine.current_content_route = ContentRoute.VLM_OCR.value

    assert engine._should_force_tier4(Path("croquis.pdf"), baseline=MagicMock()) is True


def test_other_routes_do_not_force_tier4():
    """A non-vlm content route must not force the VLM tier on its own."""
    from app.parsers.content_router import ContentRoute

    engine = _make_cascade(vlm=MagicMock(name="vlm_ocr"))

    for route in (
        ContentRoute.STANDARD_OCR.value,
        ContentRoute.INTERIOR_DESIGN.value,
        ContentRoute.PLAN_OCR.value,
        ContentRoute.TEXT_ONLY.value,
        None,
    ):
        engine.current_content_route = route
        assert engine._should_force_tier4(Path("foo.pdf"), baseline=MagicMock()) is False, (
            f"route={route!r} unexpectedly forced tier4"
        )


def test_no_vlm_engine_available_falls_through():
    """If the deployment has no VLM tier wired in, forcing is impossible."""
    from app.parsers.content_router import ContentRoute

    engine = _make_cascade(vlm=None)
    engine.current_content_route = ContentRoute.VLM_OCR.value

    assert engine._should_force_tier4(Path("croquis.pdf"), baseline=MagicMock()) is False
