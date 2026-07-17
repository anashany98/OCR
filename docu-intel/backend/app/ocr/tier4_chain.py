"""Compatible Tier 4 chain for optional remote/VLM OCR engines."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from app.ocr.base import BaseOCREngine, OCRResult
from app.ocr.ovisocr2 import OvisOCR2InputTooLarge, OvisOCR2NotEligible

logger = logging.getLogger("app.ocr.tier4_chain")


class Tier4EngineChain:
    """Try ordered Tier 4 candidates without changing the public OCR API.

    The chain intentionally falls through only for transport failures,
    ineligibility, or empty/invalid output.  Candidate selection remains the
    deterministic responsibility of ``CascadingOCREngine`` and
    ``ocr_decision``; a later VLM must not replace a coherent first candidate
    just because it emitted more prose.
    """

    name = "tier4_chain"

    def __init__(self, engines: list[BaseOCREngine], *, max_total_seconds: float) -> None:
        if not engines:
            raise ValueError("Tier4EngineChain requires at least one engine")
        self.engines = list(engines)
        self.max_total_seconds = max_total_seconds
        self._tls = threading.local()

    @property
    def current_engine(self) -> str:
        return getattr(self._tls, "current_engine", self.name)

    @property
    def last_attempts(self) -> list[dict[str, str]]:
        return list(getattr(self._tls, "last_attempts", []))

    def set_context(self, **context: object) -> None:
        self._tls.context = context
        for engine in self.engines:
            setter = getattr(engine, "set_context", None)
            if callable(setter):
                setter(**context)

    def should_force_tier4(self, image_path: Path) -> bool:
        for engine in self.engines:
            predicate = getattr(engine, "should_force_tier4", None)
            if callable(predicate) and predicate(image_path):
                return True
        return False

    def _set_attempt_context(self, engine: BaseOCREngine, deadline: float) -> None:
        """Give deadline-aware engines the remaining chain budget.

        The base OCR protocol deliberately has no timeout argument.  Engines
        that opt in (currently OvisOCR2) therefore receive the absolute
        monotonic deadline as contextual metadata; legacy engines continue to
        use their own bounded clients unchanged.
        """
        setter = getattr(engine, "set_context", None)
        if not callable(setter):
            return
        context = dict(getattr(self._tls, "context", {}))
        context["chain_deadline_monotonic"] = deadline
        try:
            setter(**context)
        except TypeError:
            # An optional context hook must never make a legacy Tier 4 engine
            # unusable merely because it does not accept extension metadata.
            logger.debug("Tier 4 engine %s does not accept chain context", engine.name)

    def extract(self, image_path: Path) -> OCRResult:
        deadline = time.monotonic() + self.max_total_seconds
        attempts: list[dict[str, str]] = []
        last_error: Exception | None = None
        for engine in self.engines:
            if time.monotonic() >= deadline:
                attempts.append({"engine": engine.name, "outcome": "chain_timeout"})
                break
            try:
                self._set_attempt_context(engine, deadline)
                result = engine.extract(image_path)
            except OvisOCR2InputTooLarge as exc:
                # A PDF DPI retry outside Ovis' pixel budget is outside the
                # safe budget for every Tier 4 VLM in this chain. Do not hand
                # the huge render to the legacy fallback; the classical OCR
                # result remains available to the cascade instead.
                attempts.append({"engine": engine.name, "outcome": "input_too_large"})
                self._tls.last_attempts = attempts
                logger.debug("Tier 4 image %s is too large: %s", image_path.name, exc)
                raise
            except OvisOCR2NotEligible as exc:
                attempts.append({"engine": engine.name, "outcome": "not_eligible"})
                logger.debug("Tier 4 engine %s skipped page: %s", engine.name, exc)
                continue
            except Exception as exc:  # noqa: BLE001 - fall through to an independent engine
                attempts.append({"engine": engine.name, "outcome": "failure"})
                last_error = exc
                logger.warning("Tier 4 engine %s failed: %s", engine.name, exc)
                continue
            if time.monotonic() > deadline:
                attempts.append({"engine": engine.name, "outcome": "chain_timeout"})
                last_error = TimeoutError("Tier 4 chain time budget exhausted")
                break
            if not (result.text or "").strip() or "empty_output" in result.warnings:
                attempts.append({"engine": engine.name, "outcome": "invalid_output"})
                last_error = RuntimeError(f"Tier 4 engine {engine.name} returned no usable text")
                continue
            result.engine = result.engine or engine.name
            self._tls.current_engine = result.engine
            attempts.append({"engine": result.engine, "outcome": "success"})
            self._tls.last_attempts = attempts
            return result
        self._tls.last_attempts = attempts
        if last_error is not None:
            raise last_error
        raise RuntimeError("No Tier 4 engine was eligible for this page")


__all__ = ["Tier4EngineChain"]
