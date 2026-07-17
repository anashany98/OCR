"""HTTP adapter for the isolated OvisOCR2 inference service."""

from __future__ import annotations

import json
import logging
import mimetypes
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from app.core.config import settings
from app.ocr.base import OCRResult
from app.ocr.ovisocr2_output import parse_ovisocr2_output
from app.ocr.routing import OvisOCR2Eligibility, ovisocr2_eligibility
from app.services.circuit_breaker import CircuitBreaker, CircuitBreakerOpen
from app.services.metrics.ocr import track_ovisocr2_output_feature, track_ovisocr2_request

logger = logging.getLogger("app.ocr.ovisocr2")


class OvisOCR2Error(RuntimeError):
    """Recoverable remote-service failure; the tier chain should continue."""


class OvisOCR2NotEligible(OvisOCR2Error):
    """Normal control-flow signal used by the Tier 4 chain."""


class OvisOCR2InputTooLarge(OvisOCR2NotEligible):
    """The rendered page exceeds the shared Tier 4 image safety budget."""


@dataclass(frozen=True)
class OvisOCR2Config:
    enabled: bool
    endpoint: str
    model: str
    revision: str
    timeout_seconds: float
    connect_timeout_seconds: float
    max_tokens: int
    max_response_bytes: int
    keep_visual_regions: bool
    max_pixels: int = 8_294_400
    api_key: str | None = None
    circuit_failures: int = 3
    circuit_reset_seconds: float = 120.0
    canary_percent: int = 0
    tier4_primary: bool = False

    @classmethod
    def from_settings(cls) -> OvisOCR2Config:
        return cls(
            enabled=settings.ovisocr2_enabled,
            endpoint=settings.ovisocr2_endpoint,
            model=settings.ovisocr2_model,
            revision=settings.ovisocr2_model_revision,
            timeout_seconds=settings.ovisocr2_timeout_seconds,
            connect_timeout_seconds=settings.ovisocr2_connect_timeout_seconds,
            max_tokens=settings.ovisocr2_max_tokens,
            max_response_bytes=settings.ovisocr2_max_response_bytes,
            keep_visual_regions=settings.ovisocr2_keep_visual_regions,
            max_pixels=settings.ovisocr2_max_pixels,
            api_key=settings.ovisocr2_api_key or None,
            circuit_failures=settings.ovisocr2_circuit_failures,
            circuit_reset_seconds=settings.ovisocr2_circuit_reset_seconds,
            canary_percent=settings.ovisocr2_canary_percent,
            tier4_primary=settings.ovisocr2_tier4_primary,
        )


class OvisOCR2Engine:
    """Stateless-per-page adapter that preserves ``BaseOCREngine`` exactly."""

    name = "ovisocr2"

    def __init__(
        self, config: OvisOCR2Config | None = None, *, client: httpx.Client | None = None
    ) -> None:
        self.config = config or OvisOCR2Config.from_settings()
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
            name="ovisocr2",
        )
        self._tls = threading.local()

    def close(self) -> None:
        self._client.close()

    def set_context(
        self,
        *,
        document_id: int | str | None = None,
        page_number: int | None = None,
        content_route: str | None = None,
        baseline: OCRResult | None = None,
        chain_deadline_monotonic: float | None = None,
    ) -> None:
        self._tls.document_id = document_id
        self._tls.page_number = page_number
        self._tls.content_route = content_route
        self._tls.baseline = baseline
        self._tls.chain_deadline_monotonic = chain_deadline_monotonic

    def eligibility(self, image_path: Path) -> OvisOCR2Eligibility:
        return ovisocr2_eligibility(
            image_path,
            baseline=getattr(self._tls, "baseline", None),
            content_route=getattr(self._tls, "content_route", None),
            document_id=getattr(self._tls, "document_id", None),
            page_number=getattr(self._tls, "page_number", None),
            canary_percent=self.config.canary_percent,
            tier4_primary=self.config.tier4_primary,
        )

    def should_force_tier4(self, image_path: Path) -> bool:
        return self.config.enabled and self.eligibility(image_path).reason == "stable_canary"

    def extract(self, image_path: Path) -> OCRResult:
        if not self.config.enabled:
            raise OvisOCR2NotEligible("OvisOCR2 is disabled")
        eligibility = self.eligibility(image_path)
        if not eligibility.eligible:
            track_ovisocr2_request("not_eligible", eligibility.reason)
            raise OvisOCR2NotEligible(f"OvisOCR2 not eligible: {eligibility.reason}")
        input_pixels = self._input_pixels(image_path)
        if input_pixels is not None and input_pixels > self.config.max_pixels:
            reason = "input_pixels_exceed_limit"
            track_ovisocr2_request("not_eligible", reason)
            raise OvisOCR2InputTooLarge(
                f"OvisOCR2 image has {input_pixels} pixels; limit is {self.config.max_pixels}"
            )
        try:
            started = time.perf_counter()
            data = self._breaker.call(self._post_with_retry, image_path)
            elapsed = time.perf_counter() - started
        except CircuitBreakerOpen as exc:
            track_ovisocr2_request("circuit_open", eligibility.reason)
            raise OvisOCR2Error(str(exc)) from exc
        except (httpx.HTTPError, OvisOCR2Error) as exc:
            track_ovisocr2_request("failure", eligibility.reason)
            raise OvisOCR2Error(str(exc)) from exc

        result = self._to_result(data, image_path)
        track_ovisocr2_request("success", eligibility.reason, elapsed)
        return result

    @staticmethod
    def _input_pixels(image_path: Path) -> int | None:
        """Inspect dimensions locally so PDF DPI retries do not hit the API limit.

        The service remains the authority for malformed/unsupported images.
        Returning ``None`` for an unreadable file deliberately preserves that
        service-side validation path and its controlled fallback behaviour.
        """
        try:
            from PIL import Image

            with Image.open(image_path) as image:
                width, height = image.size
            return width * height
        except Exception:  # noqa: BLE001 - the remote boundary handles invalid bytes
            return None

    def _post_with_retry(self, image_path: Path) -> dict[str, Any]:
        """Retry one bounded time for transport and server-side failures only."""
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                return self._post(image_path)
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code if exc.response is not None else 0
                # 4xx means our page/request is invalid.  Retrying it would
                # amplify load and mask an integration bug; 429 is also left
                # to the cascade/circuit breaker rather than blindly queued.
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
        raise OvisOCR2Error("OvisOCR2 retry loop exited unexpectedly")

    def _post(self, image_path: Path) -> dict[str, Any]:
        if not image_path.is_file():
            raise OvisOCR2Error("OCR image does not exist")
        mime = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
        headers = {"Authorization": f"Bearer {self.config.api_key}"} if self.config.api_key else {}
        data = {
            "schema_version": "1",
            "request_id": str(uuid.uuid4()),
            "document_id": str(getattr(self._tls, "document_id", ""))
            if getattr(self._tls, "document_id", None) is not None
            else "",
            "page_number": str(getattr(self._tls, "page_number", ""))
            if getattr(self._tls, "page_number", None) is not None
            else "",
            "max_tokens": str(self.config.max_tokens),
        }
        deadline = getattr(self._tls, "chain_deadline_monotonic", None)
        remaining = self.config.timeout_seconds
        if deadline is not None:
            remaining = min(remaining, deadline - time.monotonic())
            if remaining <= 0:
                raise OvisOCR2Error("Tier 4 chain time budget exhausted before OvisOCR2 request")
        request_timeout = httpx.Timeout(
            connect=min(self.config.connect_timeout_seconds, remaining),
            read=remaining,
            write=min(self.config.connect_timeout_seconds, remaining),
            pool=min(self.config.connect_timeout_seconds, remaining),
        )
        with (
            image_path.open("rb") as image,
            self._client.stream(
                "POST",
                f"{self.config.endpoint.rstrip('/')}/v1/ocr",
                data=data,
                files={"image": (image_path.name, image, mime)},
                headers=headers,
                timeout=request_timeout,
            ) as response,
        ):
            response.raise_for_status()
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > self.config.max_response_bytes:
                    raise OvisOCR2Error("OvisOCR2 response exceeds configured byte limit")
        try:
            payload = json.loads(body)
        except (TypeError, ValueError) as exc:
            raise OvisOCR2Error("OvisOCR2 response is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise OvisOCR2Error("OvisOCR2 returned a non-object JSON response")
        return payload

    def _to_result(self, payload: dict[str, Any], image_path: Path) -> OCRResult:
        if payload.get("schema_version") != "1":
            raise OvisOCR2Error("Unsupported OvisOCR2 schema version")
        if payload.get("model") != self.config.model:
            raise OvisOCR2Error("OvisOCR2 response model does not match configuration")
        if payload.get("revision") != self.config.revision:
            raise OvisOCR2Error("OvisOCR2 response revision does not match pinned configuration")
        markdown = payload.get("markdown")
        if not isinstance(markdown, str):
            raise OvisOCR2Error("OvisOCR2 response lacks markdown")
        try:
            from PIL import Image

            with Image.open(image_path) as image:
                width, height = image.size
        except Exception as exc:  # noqa: BLE001 - a valid service result still must not invent boxes
            logger.warning("Could not inspect OvisOCR2 image dimensions: %s", exc)
            width, height = 0, 0
        parsed = parse_ovisocr2_output(
            markdown,
            image_width=float(width),
            image_height=float(height),
            finish_reason=str(payload.get("finish_reason") or ""),
            keep_visual_regions=self.config.keep_visual_regions and width > 0 and height > 0,
        )
        response_warnings = payload.get("warnings")
        warnings = [*parsed.warnings]
        if isinstance(response_warnings, list):
            warnings.extend(
                str(warning)[:80] for warning in response_warnings if isinstance(warning, str)
            )
        # ``finish_reason=length`` is represented both by the service contract
        # and by the defensive local parser. Keep one ordered warning so a
        # single truncation does not inflate benchmark/telemetry counts.
        warnings = list(dict.fromkeys(warnings))
        for block in parsed.blocks:
            if block.block_type in {"text", "table", "formula", "figure"}:
                track_ovisocr2_output_feature(block.block_type)
        for warning in warnings:
            feature = {
                "truncated_output": "truncated",
                "repetitive_tail_removed": "repetitive",
                "empty_output": "empty",
                "invalid_visual_region": "invalid_region",
            }.get(warning)
            if feature:
                track_ovisocr2_output_feature(feature)
        return OCRResult(
            text=parsed.markdown,
            confidence=None,
            blocks=parsed.blocks,
            engine=self.name,
            engine_version=f"ovisocr2:{str(payload.get('revision') or self.config.revision)}",
            warnings=warnings,
        )


__all__ = [
    "OvisOCR2Config",
    "OvisOCR2Engine",
    "OvisOCR2Error",
    "OvisOCR2InputTooLarge",
    "OvisOCR2NotEligible",
]
