"""HTTP adapter for the isolated ``docling-serve`` PDF parser.

This module follows the same contract as :mod:`app.ocr.ovisocr2` so the
two external services feel identical to the rest of the codebase:

* A frozen :class:`DoclingConfig` dataclass built from
  :data:`app.core.config.settings` via :meth:`from_settings`.
* A reusable :class:`httpx.Client` with granular timeouts (connect /
  read / write / pool).
* A per-instance :class:`~app.services.circuit_breaker.CircuitBreaker`
  named ``"docling"``.
* A bounded retry that re-attempts 5xx + transport errors and never
  retries 4xx (the request would only fail the same way).
* A streaming :func:`httpx.Client.stream` POST with an explicit byte
  cap so an oversized Docling response cannot OOM the worker.
* A :func:`track_docling_request` call on every request so the
  operator can see the service health in ``/metrics``.

The class never imports ``docling`` / ``torch`` / ``transformers``;
the backend stays light and the only thing that talks to
``docling-serve`` is this module.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from app.core.config import settings
from app.services.circuit_breaker import CircuitBreaker, CircuitBreakerOpen
from app.services.metrics.ocr import track_docling_pages, track_docling_request

logger = logging.getLogger("app.services.docling_client")


class DoclingError(RuntimeError):
    """Recoverable remote-service failure; the parser router falls back
    to the legacy PDF parser when this is raised."""


class DoclingNotEligible(DoclingError):
    """Normal control-flow signal: the document is not a PDF, the
    service is disabled, or the configuration is missing."""


class DoclingTimeout(DoclingError):
    """Raised on a read/connect timeout so the router can fall back
    to the legacy parser and the metric counter can record a
    distinct outcome."""


@dataclass(frozen=True)
class DoclingConfig:
    enabled: bool
    endpoint: str
    api_key: str | None
    timeout_seconds: float
    connect_timeout_seconds: float
    max_response_bytes: int
    circuit_failures: int
    circuit_reset_seconds: float
    table_mode: str
    image_export_mode: str
    model_version: str

    @classmethod
    def from_settings(cls) -> DoclingConfig:
        return cls(
            enabled=settings.docling_enabled,
            endpoint=settings.docling_endpoint,
            api_key=settings.docling_api_key or None,
            timeout_seconds=settings.docling_timeout_seconds,
            connect_timeout_seconds=settings.docling_connect_timeout_seconds,
            max_response_bytes=settings.docling_max_response_bytes,
            circuit_failures=settings.docling_circuit_failures,
            circuit_reset_seconds=settings.docling_circuit_reset_seconds,
            table_mode=settings.docling_table_mode,
            image_export_mode=settings.docling_image_export_mode,
            model_version=settings.docling_model_version,
        )


class DoclingClient:
    """Synchronous HTTP client for ``docling-serve`` (``/v1/convert/file``).

    The class is intentionally a thin wrapper around :mod:`httpx`: the
    router only needs :meth:`is_configured` and :meth:`convert_pdf`, the
    tests need the ability to inject a :class:`httpx.MockTransport`,
    and the metrics need a single, predictable entry point.
    """

    name = "docling"

    def __init__(
        self,
        config: DoclingConfig | None = None,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self.config = config or DoclingConfig.from_settings()
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(
                connect=self.config.connect_timeout_seconds,
                read=self.config.timeout_seconds,
                write=self.config.connect_timeout_seconds,
                pool=self.config.connect_timeout_seconds,
            )
        )
        self._breaker = CircuitBreaker(
            fail_max=self.config.circuit_failures,
            reset_timeout=self.config.circuit_reset_seconds,
            name="docling",
        )

    def close(self) -> None:
        self._client.close()

    # ------------------------------------------------------------------
    # Introspection helpers
    # ------------------------------------------------------------------
    @classmethod
    def is_configured(cls) -> bool:
        """Return True when the parser router should consider Docling.

        Both the master switch and a non-empty endpoint are required:
        a deployment that flips ``DOCLING_ENABLED=true`` without
        updating ``DOCLING_ENDPOINT`` should still route to the
        legacy parser instead of failing every PDF.
        """
        return bool(settings.docling_enabled and settings.docling_endpoint)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    def convert_pdf(
        self,
        path: Path,
        *,
        do_ocr: bool = False,
        to_formats: tuple[str, ...] = ("md", "json"),
        image_export_mode: str | None = None,
        table_mode: str | None = None,
    ) -> dict[str, Any]:
        """Upload a PDF to ``docling-serve`` and return its JSON payload.

        Returns the parsed JSON document (Docling's ``DoclingDocument``
        with ``md_content`` / ``texts`` / ``tables`` / ``pictures`` /
        ``pages``). Raises :class:`DoclingError` on any failure; the
        router catches the error and falls back to the legacy PDF
        parser.

        Parameters
        ----------
        do_ocr:
            Forwarded to ``docling-serve``. Defaults to ``False`` so
            scanned pages are still passed to the legacy cascade by
            the parser; this also dodges bug #567 in
            ``docling-serve`` where ``ocr_engine`` is ignored on
            ``/v1/convert/file``.
        to_formats:
            Output serialisations to request. Defaults to
            ``("md", "json")`` — markdown for chunking-friendly text,
            JSON for the structured layout.
        image_export_mode:
            Overrides :attr:`DoclingConfig.image_export_mode`; default
            ``"referenced"`` keeps the response small.
        table_mode:
            Overrides :attr:`DoclingConfig.table_mode`; default
            ``"accurate"`` favours table quality over speed.
        """
        if not self.config.enabled:
            raise DoclingNotEligible("docling is disabled")
        if not path.is_file():
            raise DoclingNotEligible(f"file not found: {path}")

        effective_image_export_mode = image_export_mode or self.config.image_export_mode
        effective_table_mode = table_mode or self.config.table_mode

        started = time.perf_counter()
        try:
            data = self._breaker.call(
                self._post_with_retry,
                path,
                do_ocr=do_ocr,
                to_formats=to_formats,
                image_export_mode=effective_image_export_mode,
                table_mode=effective_table_mode,
            )
        except CircuitBreakerOpen as exc:
            elapsed = time.perf_counter() - started
            track_docling_request("circuit_open", "circuit_open", elapsed)
            raise DoclingError(str(exc)) from exc
        except httpx.TimeoutException as exc:
            elapsed = time.perf_counter() - started
            track_docling_request("timeout", type(exc).__name__, elapsed)
            raise DoclingTimeout(str(exc)) from exc
        except (httpx.HTTPStatusError, DoclingError) as exc:
            elapsed = time.perf_counter() - started
            reason = _failure_reason(exc)
            track_docling_request("failure", reason, elapsed)
            raise DoclingError(str(exc)) from exc
        except httpx.HTTPError as exc:
            elapsed = time.perf_counter() - started
            track_docling_request("failure", type(exc).__name__, elapsed)
            raise DoclingError(str(exc)) from exc

        elapsed = time.perf_counter() - started
        # Bookkeeping for the per-page digital/scanned split. The
        # counter is intentionally a separate metric so the
        # operator can compare Docling's page mix against the
        # legacy parser without polluting the request counter.
        try:
            digital, scanned = self._page_kind_split(data)
            track_docling_pages(digital=digital, scanned=scanned)
        except Exception:  # noqa: BLE001 — never let metrics break the parser
            logger.debug("docling page-kind split failed", exc_info=True)
        track_docling_request("success", "ok", elapsed)
        return data

    # ------------------------------------------------------------------
    # HTTP layer
    # ------------------------------------------------------------------
    def _post_with_retry(
        self,
        path: Path,
        *,
        do_ocr: bool,
        to_formats: tuple[str, ...],
        image_export_mode: str,
        table_mode: str,
    ) -> dict[str, Any]:
        """One bounded retry for 5xx + transport errors; never for 4xx.

        The retry budget is 2 attempts. The backoff is intentionally
        fixed (0.2s) — Docling requests are expensive, and the
        circuit breaker is the proper mechanism for sustained
        failure, not blind retry storms.
        """
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                return self._post(
                    path,
                    do_ocr=do_ocr,
                    to_formats=to_formats,
                    image_export_mode=image_export_mode,
                    table_mode=table_mode,
                )
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code if exc.response is not None else 0
                # 4xx means our request is invalid. Retrying would
                # amplify load and mask an integration bug. 5xx is
                # the legitimate retry target.
                if status < 500 or attempt:
                    raise
                last_error = exc
            except httpx.TransportError as exc:
                if attempt:
                    raise
                last_error = exc
            time.sleep(0.2)
        if last_error is not None:
            raise last_error
        raise DoclingError("docling retry loop exited unexpectedly")

    def _post(
        self,
        path: Path,
        *,
        do_ocr: bool,
        to_formats: tuple[str, ...],
        image_export_mode: str,
        table_mode: str,
    ) -> dict[str, Any]:
        mime = mimetypes.guess_type(path.name)[0] or "application/pdf"
        headers: dict[str, str] = {}
        if self.config.api_key:
            # docling-serve authenticates with an ``X-API-Key`` header (the
            # same convention its own CLI/Gradio UI uses), NOT an
            # ``Authorization: Bearer`` header. Sending the latter returns
            # 401 even with the correct secret, which would silently force
            # every PDF through the legacy fallback.
            headers["X-API-Key"] = self.config.api_key

        # Form fields documented at https://github.com/docling-project/docling-serve.
        # ``do_ocr=False`` is the key opt-out: the parser handles
        # scanned pages with the legacy cascade so Docling is purely
        # responsible for layout + digital text + table extraction.
        #
        # ``to_formats`` is a list on the FastAPI side
        # (``list[OutputFormat]``). A multipart list is encoded as
        # repeated fields with the same key (``to_formats=md`` +
        # ``to_formats=json``), NOT a single comma-joined string —
        # the latter is rejected with 422 because ``"md,json"`` is
        # not a valid ``OutputFormat`` enum value. httpx serialises a
        # dict value that is a list as repeated multipart fields.
        form_data: dict[str, str | list[str]] = {
            "do_ocr": "true" if do_ocr else "false",
            "to_formats": list(to_formats),
            "image_export_mode": image_export_mode,
            "table_mode": table_mode,
        }
        url = f"{self.config.endpoint.rstrip('/')}/v1/convert/file"

        with (
            path.open("rb") as payload,
            self._client.stream(
                "POST",
                url,
                data=form_data,
                files={"files": (path.name, payload, mime)},
                headers=headers,
                timeout=httpx.Timeout(
                    connect=self.config.connect_timeout_seconds,
                    read=self.config.timeout_seconds,
                    write=self.config.connect_timeout_seconds,
                    pool=self.config.connect_timeout_seconds,
                ),
            ) as response,
        ):
            response.raise_for_status()
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > self.config.max_response_bytes:
                    raise DoclingError("docling response exceeds configured byte limit")
        try:
            payload_json = json.loads(body)
        except (TypeError, ValueError) as exc:
            raise DoclingError("docling response is not valid JSON") from exc
        if not isinstance(payload_json, dict):
            raise DoclingError("docling returned a non-object JSON response")
        return payload_json

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _page_kind_split(payload: dict[str, Any]) -> tuple[int, int]:
        """Return ``(digital_pages, scanned_pages)`` for the metrics.

        ``docling-serve`` ships the DoclingDocument either inline or
        serialised as a JSON string under ``document.json_content``;
        we deserialise both so the typed lists are always reachable.
        The text lives on the flat ``texts`` / ``tables`` / ``pictures``
        lists, each item carrying its page number in ``prov[].page_no``
        (``pages`` entries only hold geometry). We regroup the items'
        text by page, then apply the same 30-char threshold the parser
        uses to decide digital vs scanned, so the two counters match
        what the parser actually did.

        Falls back to ``(0, 0)`` on any structural mismatch: the
        caller is metrics-only and must never let a quirky
        Docling payload break the parser.
        """
        doc = payload.get("document") if isinstance(payload, dict) else None
        if not isinstance(doc, dict):
            return 0, 0
        # The typed lists live inside ``json_content`` — either as a
        # dict (inline JSON) or a serialised string.
        json_content = doc.get("json_content")
        if isinstance(json_content, dict):
            doc = json_content
        elif isinstance(json_content, str) and json_content.strip():
            try:
                inner = json.loads(json_content)
            except (TypeError, ValueError):
                inner = None
            if isinstance(inner, dict):
                doc = inner
        page_texts: dict[int, str] = {}
        for key in ("texts", "tables", "pictures"):
            entries = doc.get(key)
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                text = entry.get("text") or entry.get("md_content") or ""
                if not isinstance(text, str):
                    continue
                page_no = _item_page_no(entry)
                if page_no is None:
                    continue
                page_texts.setdefault(page_no, "")
                if text:
                    page_texts[page_no] = f"{page_texts[page_no]}\n{text}".strip()
        if not page_texts:
            return 0, 0
        digital = sum(1 for text in page_texts.values() if len(text) >= 30)
        scanned = sum(1 for text in page_texts.values() if len(text) < 30)
        return digital, scanned


def _item_page_no(item: dict[str, Any]) -> int | None:
    """Return the 1-based page number a Docling item belongs to."""
    prov = item.get("prov")
    if isinstance(prov, list):
        for entry in prov:
            if isinstance(entry, dict):
                for key in ("page_no", "page"):
                    value = entry.get(key)
                    if isinstance(value, int) and value >= 1:
                        return value
    for key in ("page_no", "page"):
        value = item.get(key)
        if isinstance(value, int) and value >= 1:
            return value
    return None


def _failure_reason(exc: BaseException) -> str:
    """Return a bounded, low-cardinality reason label for a failure.

    Prometheus label cardinality must stay bounded, so the reason is
    derived from the exception **class** (``TimeoutException``,
    ``ReadError``, ``HTTPStatusError``...) rather than the message.
    Status errors additionally carry the HTTP status code, which is
    the most useful diagnostic without exploding the label space.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", 0) or 0
        return f"http_{status}"
    name = type(exc).__name__
    return name[:64]


__all__ = [
    "DoclingConfig",
    "DoclingClient",
    "DoclingError",
    "DoclingNotEligible",
    "DoclingTimeout",
    "_item_page_no",
]
