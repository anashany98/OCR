"""Unit tests for :mod:`app.services.docling_client`.

These tests cover the surface that the parser router depends on:

* :class:`DoclingConfig` is built from settings without mutating them.
* :meth:`DoclingClient.is_configured` honours the master switch.
* Multipart upload reaches ``/v1/convert/file`` with the expected
  form fields (``do_ocr=false``, ``to_formats=md,json``, …) — verified
  against the **real** parsed body, not just the content-type header.
* The 4xx-vs-5xx retry policy: 4xx is a single attempt, 5xx retries
  once before failing.
* The circuit breaker opens after the configured number of failures.
* Read timeouts surface as :class:`DoclingTimeout` with a distinct
  metric outcome.
* The byte cap aborts an oversized streaming response.
* The page-kind helper understands Docling's real schema (flat
  ``texts``/``tables``/``pictures`` with ``prov[].page_no``).
* ``convert_pdf`` accepts the documented keyword-only overrides.
* ``api_key`` is sent as a ``Bearer`` header.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from app.services.docling_client import (
    DoclingClient,
    DoclingConfig,
    DoclingError,
    DoclingNotEligible,
    DoclingTimeout,
    _item_page_no,
)
from app.services.metrics.ocr import DOCLING_FALLBACK, DOCLING_PAGES, DOCLING_REQUESTS


def _config(**overrides: Any) -> DoclingConfig:
    values: dict[str, Any] = dict(
        enabled=True,
        endpoint="http://docling-serve:5001",
        api_key=None,
        timeout_seconds=10.0,
        connect_timeout_seconds=1.0,
        max_response_bytes=1_000_000,
        circuit_failures=3,
        circuit_reset_seconds=120.0,
        table_mode="accurate",
        image_export_mode="referenced",
        model_version="",
    )
    values.update(overrides)
    return DoclingConfig(**values)


def _write_pdf(path: Path) -> None:
    """Write a minimal valid PDF so the upload has a real payload."""
    import fitz

    doc = fitz.open()
    doc.new_page()
    doc.save(str(path))
    doc.close()


def _docling_ok_payload(*, page_texts: list[str]) -> dict[str, Any]:
    """Return a Docling response shaped like the real ``/v1/convert/file``.

    The real payload puts the typed lists (``texts``/``tables``/
    ``pictures``) **inside** ``document.json_content`` as a serialised
    JSON string — not inline on ``document``. Each item's page number
    lives in ``prov[].page_no``. This fixture mirrors that so the
    page-kind split and any schema-sensitive parsing are exercised
    against the truth.
    """
    texts = []
    pages: dict[str, Any] = {}
    for idx, text in enumerate(page_texts):
        page_no = idx + 1
        texts.append(
            {
                "label": "paragraph",
                "text": text,
                "prov": [
                    {
                        "page_no": page_no,
                        "bbox": {
                            "l": 50.0,
                            "t": 50.0,
                            "r": 545.0,
                            "b": 800.0,
                            "coord_origin": "TOPLEFT",
                        },
                    }
                ],
            }
        )
        pages[str(page_no)] = {"page_no": page_no, "size": {"width": 595.0, "height": 842.0}}
    inner = {"texts": texts, "pages": pages}
    return {
        "document": {
            "json_content": inner,
            "md_content": "\n\n".join(page_texts),
        },
        "md_content": "\n\n".join(page_texts),
        "status": "success",
    }


# ---------------------------------------------------------------------------
# Config + is_configured
# ---------------------------------------------------------------------------


def test_config_reads_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import config as config_module

    monkeypatch.setattr(config_module.settings, "docling_enabled", True)
    monkeypatch.setattr(config_module.settings, "docling_endpoint", "http://svc:5001")
    monkeypatch.setattr(config_module.settings, "docling_api_key", "secret")
    monkeypatch.setattr(config_module.settings, "docling_timeout_seconds", 99.0)
    monkeypatch.setattr(config_module.settings, "docling_connect_timeout_seconds", 3.0)
    monkeypatch.setattr(config_module.settings, "docling_max_response_bytes", 2_000_000)
    monkeypatch.setattr(config_module.settings, "docling_circuit_failures", 5)
    monkeypatch.setattr(config_module.settings, "docling_circuit_reset_seconds", 30.0)
    monkeypatch.setattr(config_module.settings, "docling_table_mode", "fast")
    monkeypatch.setattr(config_module.settings, "docling_image_export_mode", "embedded")
    monkeypatch.setattr(config_module.settings, "docling_model_version", "v1")

    cfg = DoclingConfig.from_settings()
    assert cfg.enabled is True
    assert cfg.endpoint == "http://svc:5001"
    assert cfg.api_key == "secret"
    assert cfg.timeout_seconds == 99.0
    assert cfg.max_response_bytes == 2_000_000
    assert cfg.circuit_failures == 5
    assert cfg.table_mode == "fast"
    assert cfg.image_export_mode == "embedded"


def test_is_configured_requires_both_switch_and_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import config as config_module

    monkeypatch.setattr(config_module.settings, "docling_enabled", False)
    monkeypatch.setattr(config_module.settings, "docling_endpoint", "http://svc:5001")
    assert DoclingClient.is_configured() is False

    monkeypatch.setattr(config_module.settings, "docling_enabled", True)
    monkeypatch.setattr(config_module.settings, "docling_endpoint", "")
    assert DoclingClient.is_configured() is False

    monkeypatch.setattr(config_module.settings, "docling_endpoint", "http://svc:5001")
    assert DoclingClient.is_configured() is True


# ---------------------------------------------------------------------------
# Multipart form fields — verified against the real parsed body
# ---------------------------------------------------------------------------


def _last_request(handler_views: list[httpx.Request]) -> httpx.Request:
    assert handler_views, "handler was never called"
    return handler_views[-1]


def test_post_sends_expected_form_fields(tmp_path: Path) -> None:
    """The multipart body must carry the documented form fields.

    This previously only asserted the content-type header; the real
    body is now inspected so a regression on ``do_ocr`` (the field that
    decides whether Docling runs its own OCR) cannot slip through.
    """
    pdf = tmp_path / "in.pdf"
    _write_pdf(pdf)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_docling_ok_payload(page_texts=["hello world"]))

    client = DoclingClient(_config(), client=httpx.Client(transport=httpx.MockTransport(handler)))
    payload = client.convert_pdf(pdf)

    request = _last_request(seen)
    assert str(request.url).endswith("/v1/convert/file")
    content_type = request.headers.get("content-type", "")
    assert "multipart/form-data" in content_type

    # Parse the multipart body to assert the actual form fields. httpx
    # exposes the raw bytes on ``request.content``; the boundary lives
    # in the content-type header.
    body = request.content
    decoded = body.decode("utf-8", errors="replace")
    assert 'name="do_ocr"' in decoded
    assert 'name="image_export_mode"' in decoded
    assert 'name="table_mode"' in decoded
    # ``to_formats`` must be repeated fields (one per format), NOT a
    # single comma-joined string — docling-serve rejects ``"md,json"``
    # with 422 because it is not a valid OutputFormat enum value.
    assert decoded.count('name="to_formats"') == 2
    assert "md,json" not in decoded
    # ``do_ocr=false`` is the key opt-out: the parser handles OCR via
    # the legacy cascade, and it dodges docling-serve bug #567.
    assert "false" in decoded
    assert "accurate" in decoded
    assert "referenced" in decoded
    assert payload["md_content"] == "hello world"


def test_convert_pdf_overrides_form_fields(tmp_path: Path) -> None:
    """Keyword-only overrides on ``convert_pdf`` reach the wire."""
    pdf = tmp_path / "in.pdf"
    _write_pdf(pdf)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_docling_ok_payload(page_texts=["ok"]))

    client = DoclingClient(_config(), client=httpx.Client(transport=httpx.MockTransport(handler)))
    client.convert_pdf(
        pdf,
        do_ocr=True,
        to_formats=("json",),
        image_export_mode="embedded",
        table_mode="fast",
    )

    decoded = _last_request(seen).content.decode("utf-8", errors="replace")
    assert "true" in decoded
    # A single ``to_formats=json`` field (no comma-joined form).
    assert 'name="to_formats"' in decoded
    assert "md" not in decoded or decoded.count('name="to_formats"') == 1
    assert "json" in decoded
    assert "embedded" in decoded
    assert "fast" in decoded


def test_api_key_is_sent_as_x_api_key_header(tmp_path: Path) -> None:
    pdf = tmp_path / "in.pdf"
    _write_pdf(pdf)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_docling_ok_payload(page_texts=["ok"]))

    client = DoclingClient(
        _config(api_key="tok-123"),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    client.convert_pdf(pdf)
    # docling-serve authenticates with X-API-Key, not Authorization: Bearer.
    request = _last_request(seen)
    assert request.headers.get("x-api-key") == "tok-123"
    assert request.headers.get("authorization") is None


# ---------------------------------------------------------------------------
# Retry policy: 4xx vs 5xx
# ---------------------------------------------------------------------------


def test_convert_pdf_does_not_retry_4xx(tmp_path: Path) -> None:
    pdf = tmp_path / "in.pdf"
    _write_pdf(pdf)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(422, json={"detail": "invalid"})

    client = DoclingClient(_config(), client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(DoclingError):
        client.convert_pdf(pdf)
    assert calls == 1


def test_convert_pdf_retries_5xx_once(tmp_path: Path) -> None:
    pdf = tmp_path / "in.pdf"
    _write_pdf(pdf)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, json={"detail": "busy"})
        return httpx.Response(200, json=_docling_ok_payload(page_texts=["ok"]))

    client = DoclingClient(_config(), client=httpx.Client(transport=httpx.MockTransport(handler)))
    payload = client.convert_pdf(pdf)
    assert calls == 2
    assert payload["md_content"] == "ok"


# ---------------------------------------------------------------------------
# Timeout
# ---------------------------------------------------------------------------


def test_convert_pdf_raises_docling_timeout_on_read_timeout(tmp_path: Path) -> None:
    """A read timeout must surface as :class:`DoclingTimeout`, not a
    generic :class:`DoclingError`, so the metric outcome is distinct."""
    pdf = tmp_path / "in.pdf"
    _write_pdf(pdf)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("read timed out")

    client = DoclingClient(
        _config(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(DoclingTimeout):
        client.convert_pdf(pdf)


def test_convert_pdf_raises_docling_timeout_on_connect_timeout(tmp_path: Path) -> None:
    pdf = tmp_path / "in.pdf"
    _write_pdf(pdf)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("connect timed out")

    client = DoclingClient(
        _config(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(DoclingTimeout):
        client.convert_pdf(pdf)


# ---------------------------------------------------------------------------
# Byte cap (anti-OOM)
# ---------------------------------------------------------------------------


def test_convert_pdf_aborts_oversized_response(tmp_path: Path) -> None:
    pdf = tmp_path / "in.pdf"
    _write_pdf(pdf)
    huge = b'{"document": {"texts": [{"text": "' + b"a" * 10_000 + b'"}]}}'

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=huge,
            headers={"content-type": "application/json"},
        )

    client = DoclingClient(
        _config(max_response_bytes=1_024),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(DoclingError, match="exceeds"):
        client.convert_pdf(pdf)


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------


def test_circuit_breaker_opens_after_repeated_failures(tmp_path: Path) -> None:
    pdf = tmp_path / "in.pdf"
    _write_pdf(pdf)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "down"})

    client = DoclingClient(
        _config(circuit_failures=2),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    # Two calls to trip the breaker (each call retries once, so
    # each "call" already counts as a single breaker failure).
    with pytest.raises(DoclingError):
        client.convert_pdf(pdf)
    with pytest.raises(DoclingError):
        client.convert_pdf(pdf)

    # Third call should be rejected by the breaker before the HTTP
    # layer even sees it.
    with pytest.raises(DoclingError, match="OPEN"):
        client.convert_pdf(pdf)


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------


def test_convert_pdf_raises_on_missing_file(tmp_path: Path) -> None:
    client = DoclingClient(_config())
    with pytest.raises(DoclingNotEligible):
        client.convert_pdf(tmp_path / "ghost.pdf")


def test_convert_pdf_raises_on_disabled_config(tmp_path: Path) -> None:
    pdf = tmp_path / "in.pdf"
    _write_pdf(pdf)
    client = DoclingClient(_config(enabled=False))
    with pytest.raises(DoclingNotEligible):
        client.convert_pdf(pdf)


# ---------------------------------------------------------------------------
# Page-kind split — real schema
# ---------------------------------------------------------------------------


def test_page_kind_split_handles_flat_item_schema() -> None:
    """The real Docling schema keeps text on flat ``texts``/``tables``
    lists with ``prov[].page_no``; the helper must regroup correctly."""
    payload = _docling_ok_payload(
        page_texts=[
            "Page one has plenty of digital text content here",
            "",  # scanned (no text)
            "Third page is also digital with at least thirty characters",
        ]
    )
    digital, scanned = DoclingClient._page_kind_split(payload)
    assert digital == 2
    assert scanned == 1


def test_page_kind_split_counts_tables_with_page_no() -> None:
    payload = {
        "document": {
            "tables": [
                {
                    "label": "table",
                    "md_content": "| a | b |\n| --- | --- |\n| 1 | 2 |",
                    "prov": [{"page_no": 1, "bbox": {"l": 0, "t": 0, "r": 100, "b": 100}}],
                }
            ],
        }
    }
    digital, scanned = DoclingClient._page_kind_split(payload)
    assert digital == 1
    assert scanned == 0


def test_page_kind_split_returns_zeros_on_garbage() -> None:
    assert DoclingClient._page_kind_split({}) == (0, 0)
    assert DoclingClient._page_kind_split({"document": None}) == (0, 0)
    assert DoclingClient._page_kind_split({"document": {"pages": "oops"}}) == (0, 0)


def test_item_page_no_reads_prov_first() -> None:
    assert _item_page_no({"prov": [{"page_no": 3}]}) == 3
    assert _item_page_no({"prov": [{"page": 4}]}) == 4
    # Falls back to top-level page_no.
    assert _item_page_no({"page_no": 2}) == 2
    # Missing/invalid returns None.
    assert _item_page_no({}) is None
    assert _item_page_no({"prov": [{"page_no": "x"}]}) is None


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def test_metrics_counters_are_incremented_on_success(tmp_path: Path) -> None:
    pdf = tmp_path / "in.pdf"
    _write_pdf(pdf)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_docling_ok_payload(page_texts=["a" * 100, "b" * 100, ""]),
        )

    from prometheus_client import REGISTRY

    def _value(name: str, labels: dict[str, str]) -> float:
        sample = REGISTRY.get_sample_value(name, labels=labels)
        return float(sample) if sample is not None else 0.0

    # Touch the canonical success label so the sample exists.
    DOCLING_REQUESTS.labels(outcome="success", reason="ok").inc(0)
    DOCLING_PAGES.labels(kind="digital").inc(0)
    DOCLING_PAGES.labels(kind="scanned").inc(0)

    before_success = _value(
        "docuintel_docling_requests_total", {"outcome": "success", "reason": "ok"}
    )
    before_digital = _value("docuintel_docling_pages_total", {"kind": "digital"})
    before_scanned = _value("docuintel_docling_pages_total", {"kind": "scanned"})

    client = DoclingClient(_config(), client=httpx.Client(transport=httpx.MockTransport(handler)))
    client.convert_pdf(pdf)

    after_success = _value(
        "docuintel_docling_requests_total", {"outcome": "success", "reason": "ok"}
    )
    after_digital = _value("docuintel_docling_pages_total", {"kind": "digital"})
    after_scanned = _value("docuintel_docling_pages_total", {"kind": "scanned"})

    assert after_success - before_success == 1
    assert after_digital - before_digital == 2
    assert after_scanned - before_scanned == 1


def test_metrics_record_timeout_outcome(tmp_path: Path) -> None:
    """A timeout must record a distinct ``timeout`` outcome."""
    pdf = tmp_path / "in.pdf"
    _write_pdf(pdf)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("read timed out")

    from prometheus_client import REGISTRY

    # The metric helper lowercases + strips the reason label, so the
    # exception class name ``ReadTimeout`` lands as ``readtimeout``.
    DOCLING_REQUESTS.labels(outcome="timeout", reason="readtimeout").inc(0)
    before = REGISTRY.get_sample_value(
        "docuintel_docling_requests_total",
        labels={"outcome": "timeout", "reason": "readtimeout"},
    )

    client = DoclingClient(_config(), client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(DoclingTimeout):
        client.convert_pdf(pdf)

    after = REGISTRY.get_sample_value(
        "docuintel_docling_requests_total",
        labels={"outcome": "timeout", "reason": "readtimeout"},
    )
    assert (after or 0) - (before or 0) == 1


def test_metrics_record_http_status_reason_on_failure(tmp_path: Path) -> None:
    """A 5xx failure must record ``http_<status>`` as the reason label."""
    pdf = tmp_path / "in.pdf"
    _write_pdf(pdf)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "down"})

    from prometheus_client import REGISTRY

    DOCLING_REQUESTS.labels(outcome="failure", reason="http_503").inc(0)
    before = REGISTRY.get_sample_value(
        "docuintel_docling_requests_total",
        labels={"outcome": "failure", "reason": "http_503"},
    )

    client = DoclingClient(_config(), client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(DoclingError):
        client.convert_pdf(pdf)

    after = REGISTRY.get_sample_value(
        "docuintel_docling_requests_total",
        labels={"outcome": "failure", "reason": "http_503"},
    )
    # At least one failure recorded with the status-code reason.
    assert (after or 0) - (before or 0) >= 1


def test_fallback_counter_is_known_label() -> None:
    """Sanity check: only the bounded label set is accepted by the helper."""
    from prometheus_client import REGISTRY

    from app.services.metrics.ocr import track_docling_fallback

    DOCLING_FALLBACK.labels(reason="failure").inc(0)
    before = REGISTRY.get_sample_value(
        "docuintel_docling_fallback_total", labels={"reason": "failure"}
    )
    track_docling_fallback("failure")
    after = REGISTRY.get_sample_value(
        "docuintel_docling_fallback_total", labels={"reason": "failure"}
    )
    assert (after or 0) - (before or 0) == 1


def test_request_outcome_uses_bounded_labels() -> None:
    """The helper must bucket unknown outcomes to ``failure``."""
    from prometheus_client import REGISTRY

    from app.services.metrics.ocr import track_docling_request

    track_docling_request("totally_made_up_outcome", "n/a")
    value = REGISTRY.get_sample_value(
        "docuintel_docling_requests_total",
        labels={"outcome": "failure", "reason": "n/a"},
    )
    assert value is not None and value >= 1
