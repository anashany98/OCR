from __future__ import annotations

import base64
import logging
import random
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.core.config import settings
from app.ocr.base import OCRBlock, OCRResult
from app.services.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpen,
)

logger = logging.getLogger("app.ocr.dots_mocr")


# ---------------------------------------------------------------------------
# Circuit breaker + retry helpers (A1).
#
# The DotsMOCR endpoint is an external HTTP service: it can 5xx, drop the
# connection, or simply hang. The LLM client (ai/local_client.py) and the
# embedding client (app/services/embeddings.py) already wrap their HTTP
# calls in a ``CircuitBreaker`` + retry-with-backoff so a transient blip
# doesn't translate into a permanent "Tier 4 unavailable" outcome.
# DotsMOCR was the odd one out: a single 5xx short-circuited the
# fallback to Tier 1-3 for *every* subsequent page until the operator
# restarted the worker. A1 closes that gap.
# ---------------------------------------------------------------------------

_dots_mocr_breaker: CircuitBreaker | None = None
_dots_mocr_breaker_lock = threading.Lock()


def _get_dots_mocr_breaker() -> CircuitBreaker:
    """Return the process-wide DotsMOCR circuit breaker (lazy singleton)."""
    global _dots_mocr_breaker
    if _dots_mocr_breaker is not None:
        return _dots_mocr_breaker
    with _dots_mocr_breaker_lock:
        if _dots_mocr_breaker is None:
            _dots_mocr_breaker = CircuitBreaker(
                fail_max=settings.ai_circuit_breaker_failures,
                reset_timeout=settings.ai_circuit_breaker_reset_seconds,
                name="dots_mocr",
            )
    return _dots_mocr_breaker


def reset_dots_mocr_breaker() -> None:
    """Force the breaker back to CLOSED. Test/admin helper."""
    global _dots_mocr_breaker
    if _dots_mocr_breaker is not None:
        _dots_mocr_breaker.reset()


@dataclass(frozen=True)
class DotsMOCRConfig:
    enabled: bool = False
    endpoint: str | None = None
    api_key: str | None = None
    timeout_seconds: float = 120.0
    # A1: max retry attempts on transient HTTP errors before giving up.
    # The retry happens *inside* the breaker so each attempt counts
    # toward ``fail_max`` only on the final failure (the per-attempt
    # transport errors are absorbed by the retry loop). Default 2 = up
    # to 3 total attempts.
    max_retries: int = 2
    # A1: base delay for exponential backoff in seconds. The actual
    # sleep is ``base * 2 ** attempt + jitter``.
    retry_base_delay_seconds: float = 0.5


class DotsMOCREngine:
    name = "dots_mocr"

    def __init__(
        self,
        config: DotsMOCRConfig,
        breaker: CircuitBreaker | None = None,
    ) -> None:
        self.config = config
        # Injectable for tests; defaults to the process-wide singleton.
        self._breaker = breaker

    def extract(self, image_path: Path) -> OCRResult:
        if not self.config.enabled:
            raise RuntimeError("dots.mocr integration is disabled")
        if not self.config.endpoint:
            raise RuntimeError("dots.mocr endpoint is not configured")

        payload = {
            "filename": image_path.name,
            "image_base64": base64.b64encode(image_path.read_bytes()).decode("ascii"),
        }
        headers = (
            {"Authorization": f"Bearer {self.config.api_key}"} if self.config.api_key else None
        )

        # A1: retry-with-backoff inside the breaker. We catch
        # ``httpx.HTTPError`` (transport + 4xx/5xx) at this layer and
        # let ``CircuitBreakerOpen`` bubble up to ``cascading.py`` so the
        # cascade can fall back to Tier 1-3 immediately, the same way it
        # already does for any other Tier 4 error.
        breaker = self._breaker or _get_dots_mocr_breaker()
        data = self._call_with_retry(breaker, payload, headers)

        text = str(data.get("text") or "").strip()
        confidence = _coerce_confidence(data.get("confidence"))
        blocks = _parse_blocks(data.get("blocks"))
        if not blocks and text:
            blocks = [OCRBlock(text=text, confidence=confidence, bbox=None, block_type=None)]
        return OCRResult(text=text, confidence=confidence, blocks=blocks, engine=self.name)

    def _call_with_retry(
        self,
        breaker: CircuitBreaker,
        payload: dict,
        headers: dict | None,
    ) -> dict:
        """POST through the breaker with retry-with-backoff on 5xx / transport errors.

        4xx errors are NOT retried — they indicate a bug in our request
        shape and retrying would only amplify it. ``HTTPStatusError``
        from a 5xx or ``httpx.HTTPError`` (timeouts, connection
        drops) is what the retry loop handles.
        """
        last_exc: BaseException | None = None
        attempts = max(0, self.config.max_retries) + 1
        for attempt in range(attempts):
            try:
                return breaker.call(self._post, payload, headers)
            except CircuitBreakerOpen:
                # Service is known-down; don't waste retries, let the
                # cascade fall back to Tier 1-3 immediately.
                raise
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code if exc.response is not None else 0
                if status < 500 or attempt >= attempts - 1:
                    raise
                last_exc = exc
            except httpx.HTTPError as exc:
                if attempt >= attempts - 1:
                    raise
                last_exc = exc
            self._sleep_before_retry(attempt)
        # Unreachable: the loop either returns or raises.
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("dots_mocr retry loop exited without a result")

    def _post(self, payload: dict, headers: dict | None) -> dict:
        """Single HTTP attempt. Wrapped by the breaker in ``_call_with_retry``."""
        with httpx.Client(timeout=self.config.timeout_seconds) as client:
            response = client.post(self.config.endpoint, json=payload, headers=headers)
            response.raise_for_status()
            return response.json()

    def _sleep_before_retry(self, attempt: int) -> None:
        delay = self.config.retry_base_delay_seconds * (2**attempt)
        jitter = random.uniform(0.0, delay * 0.25)
        time.sleep(delay + jitter)


def _coerce_confidence(value: object) -> float | None:
    if value is None:
        return None
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return None


def _parse_blocks(raw_blocks: object) -> list[OCRBlock]:
    if not isinstance(raw_blocks, list):
        return []
    blocks: list[OCRBlock] = []
    for raw in raw_blocks:
        if not isinstance(raw, dict):
            continue
        text = str(raw.get("text") or "").strip()
        if not text:
            continue
        blocks.append(
            OCRBlock(
                text=text,
                confidence=_coerce_confidence(raw.get("confidence")),
                bbox=_coerce_bbox(raw.get("bbox")),
                block_type=str(raw["block_type"]) if raw.get("block_type") else None,
            )
        )
    return blocks


def _coerce_bbox(value: object) -> tuple[float, float, float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        x1, y1, x2, y2 = (float(part) for part in value)
    except (TypeError, ValueError):
        return None
    return (x1, y1, x2, y2)


__all__ = ["DotsMOCRConfig", "DotsMOCREngine"]
