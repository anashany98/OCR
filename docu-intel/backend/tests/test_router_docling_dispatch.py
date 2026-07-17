"""Router integration tests for the Docling opt-in dispatch.

These tests exercise the :func:`app.parsers.router._parse_pdf`
helper directly so the three routing decisions stay readable in
one place:

* ``PDF_PARSER=legacy`` always calls the legacy parser.
* ``PDF_PARSER=docling`` + Docling configured calls
  :func:`parse_pdf_docling` and returns its result.
* ``PDF_PARSER=docling`` + a Docling failure falls back to
  :func:`parse_pdf` and records the bounded fallback metric.

The tests are intentionally integration-light: the real Docling
service is mocked at the parser boundary so the suite stays
self-contained.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import fitz
import pytest

from app.parsers import router as router_module
from app.services.docling_client import DoclingError


def _make_pdf(path: Path, *, pages: list[str]) -> None:
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        if text:
            page.insert_text((72, 72), text)
    doc.save(str(path))
    doc.close()


@pytest.fixture
def legacy_parser() -> Any:
    """Patch :func:`app.parsers.pdf.parse_pdf` with a recording mock."""
    with patch("app.parsers.router.parse_pdf") as mock:
        mock.return_value = MagicMock(pages=[MagicMock(ocr_engine="pymupdf")])
        yield mock


@pytest.fixture
def docling_parser() -> Any:
    """Patch :func:`app.parsers.pdf_docling.parse_pdf_docling`."""
    with patch("app.parsers.router.parse_pdf_docling") as mock:
        mock.return_value = MagicMock(pages=[MagicMock(ocr_engine="docling")])
        yield mock


# ---------------------------------------------------------------------------
# PDF_PARSER=legacy
# ---------------------------------------------------------------------------


def test_legacy_parser_is_used_when_setting_is_legacy(
    tmp_path: Path,
    legacy_parser: Any,
    docling_parser: Any,
) -> None:
    pdf = tmp_path / "doc.pdf"
    _make_pdf(pdf, pages=["anything long enough to look like a real page"])
    with patch.object(router_module.settings, "pdf_parser", "legacy"):
        router_module._parse_pdf(pdf, tmp_path / "out", MagicMock(), None)
    legacy_parser.assert_called_once()
    docling_parser.assert_not_called()


def test_legacy_parser_used_when_docling_not_configured(
    tmp_path: Path,
    legacy_parser: Any,
    docling_parser: Any,
) -> None:
    """PDF_PARSER=docling but ``is_configured()`` returns False → legacy."""
    pdf = tmp_path / "doc.pdf"
    _make_pdf(pdf, pages=["any text here is fine for the test"])
    with (
        patch.object(router_module.settings, "pdf_parser", "docling"),
        patch.object(router_module.DoclingClient, "is_configured", return_value=False),
    ):
        router_module._parse_pdf(pdf, tmp_path / "out", MagicMock(), None)
    legacy_parser.assert_called_once()
    docling_parser.assert_not_called()


# ---------------------------------------------------------------------------
# PDF_PARSER=docling + Docling configured
# ---------------------------------------------------------------------------


def test_docling_parser_is_called_when_enabled(
    tmp_path: Path,
    legacy_parser: Any,
    docling_parser: Any,
) -> None:
    pdf = tmp_path / "doc.pdf"
    _make_pdf(pdf, pages=["Digital content that is long enough"])
    with (
        patch.object(router_module.settings, "pdf_parser", "docling"),
        patch.object(router_module.DoclingClient, "is_configured", return_value=True),
    ):
        result = router_module._parse_pdf(pdf, tmp_path / "out", MagicMock(), None)
    docling_parser.assert_called_once()
    legacy_parser.assert_not_called()
    # The router must hand back whatever the Docling parser produced.
    assert result is docling_parser.return_value


def test_docling_not_eligible_falls_back_to_legacy(
    tmp_path: Path,
    legacy_parser: Any,
) -> None:
    pdf = tmp_path / "doc.pdf"
    _make_pdf(pdf, pages=["text"])
    docling_parser = MagicMock(side_effect=router_module.DoclingNotEligible("disabled"))
    with (
        patch.object(router_module.settings, "pdf_parser", "docling"),
        patch.object(router_module.DoclingClient, "is_configured", return_value=True),
        patch.object(router_module, "parse_pdf_docling", docling_parser),
        patch.object(router_module, "track_docling_fallback") as fallback_metric,
    ):
        router_module._parse_pdf(pdf, tmp_path / "out", MagicMock(), None)
    legacy_parser.assert_called_once()
    fallback_metric.assert_called_once_with("not_eligible")


def test_docling_runtime_error_falls_back_to_legacy(
    tmp_path: Path,
    legacy_parser: Any,
) -> None:
    pdf = tmp_path / "doc.pdf"
    _make_pdf(pdf, pages=["text"])
    docling_parser = MagicMock(side_effect=DoclingError("service down"))
    with (
        patch.object(router_module.settings, "pdf_parser", "docling"),
        patch.object(router_module.DoclingClient, "is_configured", return_value=True),
        patch.object(router_module, "parse_pdf_docling", docling_parser),
        patch.object(router_module, "track_docling_fallback") as fallback_metric,
    ):
        router_module._parse_pdf(pdf, tmp_path / "out", MagicMock(), None)
    legacy_parser.assert_called_once()
    fallback_metric.assert_called_once_with("failure")


def test_unhandled_exception_falls_back_to_legacy(
    tmp_path: Path,
    legacy_parser: Any,
) -> None:
    """A bug in the Docling parser must not break ingestion."""
    pdf = tmp_path / "doc.pdf"
    _make_pdf(pdf, pages=["text"])
    docling_parser = MagicMock(side_effect=RuntimeError("boom"))
    with (
        patch.object(router_module.settings, "pdf_parser", "docling"),
        patch.object(router_module.DoclingClient, "is_configured", return_value=True),
        patch.object(router_module, "parse_pdf_docling", docling_parser),
        patch.object(router_module, "track_docling_fallback") as fallback_metric,
    ):
        router_module._parse_pdf(pdf, tmp_path / "out", MagicMock(), None)
    legacy_parser.assert_called_once()
    fallback_metric.assert_called_once_with("exception")


def test_parser_does_not_double_count_fallback_metric(tmp_path: Path) -> None:
    """Regression: ``parse_pdf_docling`` used to call
    ``track_docling_fallback("exception")`` itself, which the router
    then counted again — inflating the metric 2x. The router is the
    single owner of the fallback metric, so the parser must not emit
    it.

    We verify two ways: (1) the parser module does not import
    ``track_docling_fallback`` (AST-level check, robust to
    comments/docstrings), and (2) running the router end-to-end with
    a failing injected client grows the counter by exactly one.
    """
    import ast

    from app.parsers import pdf_docling as pdf_docling_module

    # (1) Structural check: walk the AST for any ``track_docling_fallback``
    # name being imported or called. Comments/docstrings are not in the
    # AST, so this is a clean signal.
    tree = ast.parse(inspect.getsource(pdf_docling_module))
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "track_docling_fallback":
            found = True
            break
        if isinstance(node, ast.Attribute) and node.attr == "track_docling_fallback":
            found = True
            break
    assert not found, "parse_pdf_docling must not reference track_docling_fallback"

    # (2) Behavioural check: a single Docling failure increments the
    # fallback counter exactly once (the router's call).
    from prometheus_client import REGISTRY

    from app.services.docling_client import DoclingError
    from app.services.metrics.ocr import DOCLING_FALLBACK

    pdf = tmp_path / "doc.pdf"
    _make_pdf(pdf, pages=["text long enough to look digital"])

    failing_client = MagicMock()
    failing_client.convert_pdf.side_effect = DoclingError("down")

    DOCLING_FALLBACK.labels(reason="failure").inc(0)
    before = REGISTRY.get_sample_value(
        "docuintel_docling_fallback_total", labels={"reason": "failure"}
    )

    with (
        patch.object(router_module.settings, "pdf_parser", "docling"),
        patch.object(router_module.DoclingClient, "is_configured", return_value=True),
        patch.object(router_module, "parse_pdf") as legacy,
    ):
        legacy.return_value = MagicMock(pages=[])

        real_parse = __import__(
            "app.parsers.pdf_docling", fromlist=["parse_pdf_docling"]
        ).parse_pdf_docling

        def _wrapped(path, output_dir, ocr_engine, folder_hint=None):  # type: ignore[no-untyped-def]
            return real_parse(
                path, output_dir, ocr_engine, folder_hint=folder_hint, docling_client=failing_client
            )

        with patch.object(router_module, "parse_pdf_docling", side_effect=_wrapped):
            router_module._parse_pdf(pdf, tmp_path / "out", MagicMock(), None)

    after = REGISTRY.get_sample_value(
        "docuintel_docling_fallback_total", labels={"reason": "failure"}
    )
    assert (after or 0) - (before or 0) == 1





# ---------------------------------------------------------------------------
# parse_document top-level dispatch
# ---------------------------------------------------------------------------


def test_parse_document_routes_pdf_through_docling(
    tmp_path: Path,
    legacy_parser: Any,
) -> None:
    pdf = tmp_path / "doc.pdf"
    _make_pdf(pdf, pages=["text"])
    with (
        patch.object(router_module.settings, "pdf_parser", "docling"),
        patch.object(router_module.DoclingClient, "is_configured", return_value=True),
        patch.object(
            router_module,
            "parse_pdf_docling",
            return_value=MagicMock(pages=[MagicMock(ocr_engine="docling")]),
        ) as docling,
    ):
        router_module.parse_document(pdf, tmp_path / "out", MagicMock())
    docling.assert_called_once()
    legacy_parser.assert_not_called()


def test_parse_document_ignores_non_pdf(
    tmp_path: Path,
    legacy_parser: Any,
) -> None:
    """A .txt file must not be sent to Docling — guard against future regressions."""
    txt = tmp_path / "doc.txt"
    txt.write_text("hello", encoding="utf-8")
    with (
        patch.object(router_module.settings, "pdf_parser", "docling"),
        patch.object(router_module.DoclingClient, "is_configured", return_value=True),
        patch.object(
            router_module,
            "parse_pdf_docling",
        ) as docling,
    ):
        router_module.parse_document(txt, tmp_path / "out", MagicMock())
    docling.assert_not_called()
