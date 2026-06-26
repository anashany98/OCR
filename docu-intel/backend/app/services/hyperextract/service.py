"""Hyper-Extract — main service.

This module implements the optional structured-extraction layer that
runs **after** the OCR has produced clean text. It is designed to be:

* **Opt-in.** Disabled by default (``HYPEREXTRACT_ENABLED=false``). When
  disabled the service is a no-op that always returns ``status="disabled"``
  and never makes a network call.
* **Provider-agnostic.** Talks OpenAI-compatible Chat Completions
  (LM Studio, vLLM, Ollama with the ``/v1`` route, OpenAI, or any
  MiniMax M3-style gateway).
* **Fail-safe.** Any exception inside the provider call is caught and
  surfaced as ``status="failed"``; the OCR pipeline keeps running and
  the original OCR text is preserved.
* **Auditable.** When ``hyperextract_persist_raw_output`` is true the
  raw provider payload is stored alongside the parsed result so an
  operator can replay or compare runs.
* **Quiet in logs.** API keys never appear in logs. The document text
  is summarised by length, never echoed.

The service never blocks the OCR path: callers should ``try/except``
around it but the service itself never raises (it always returns a
typed :class:`HyperExtractResult`).
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any

import httpx

from app.core.config import settings
from app.services.hyperextract.templates import (
    HyperExtractTemplate,
    build_field_instructions,
    list_templates,
    load_template,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Output envelope
# ---------------------------------------------------------------------------


def _empty_envelope() -> dict[str, Any]:
    """Return the canonical empty result payload.

    The shape is documented in ``docs/hyperextract.md`` and must remain
    backward-compatible: existing consumers (the API, the review panel,
    the test script) rely on the keys below.
    """
    return {
        "enabled": False,
        "status": "disabled",
        "document_id": None,
        "document_type": None,
        "fields": {},
        "entities": [],
        "relations": [],
        "raw_output": {},
        "warnings": [],
        "provider": None,
        "model": None,
        "latency_ms": 0,
    }


@dataclass
class HyperExtractResult:
    """Typed view of the canonical envelope.

    Use :meth:`to_dict` when you need a JSON-serialisable payload (API
    responses, DB persistence). The dataclass is purely for ergonomic
    access in Python.
    """

    enabled: bool = False
    status: str = "disabled"
    document_id: str | int | None = None
    document_type: str | None = None
    fields: dict[str, Any] = field(default_factory=dict)
    entities: list[Any] = field(default_factory=list)
    relations: list[Any] = field(default_factory=list)
    raw_output: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    provider: str | None = None
    model: str | None = None
    latency_ms: int = 0
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class HyperExtractService:
    """Provider client for Hyper-Extract.

    The class is stateless apart from the (cached) templates and the
    underlying ``httpx.Client``. It is safe to instantiate per-call; for
    long-running workers a single instance per process is preferable.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float | None = None,
        provider_name: str | None = None,
        output_dir: str | None = None,
        persist_raw_output: bool | None = None,
    ) -> None:
        self._base_url = (base_url if base_url is not None else settings.hyperextract_base_url).rstrip("/")
        self._model = model if model is not None else settings.hyperextract_model
        self._api_key = api_key if api_key is not None else settings.hyperextract_api_key
        self._timeout = float(
            timeout_seconds if timeout_seconds is not None else settings.hyperextract_timeout_seconds
        )
        self._provider_name = (
            provider_name if provider_name is not None else settings.hyperextract_provider
        )
        self._output_dir = output_dir if output_dir is not None else settings.hyperextract_output_dir
        self._persist_raw_output = (
            bool(persist_raw_output)
            if persist_raw_output is not None
            else bool(settings.hyperextract_persist_raw_output)
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_enabled(self) -> bool:
        """Whether the service is configured to make provider calls."""
        return bool(settings.hyperextract_enabled)

    def list_available_templates(self) -> list[str]:
        """Return the ``document_type`` of every loaded template."""
        return [t.document_type for t in list_templates()]

    def extract_from_text(
        self,
        document_id: str | int,
        text: str,
        document_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run a generic extraction and return the canonical envelope.

        ``document_type`` is optional. When omitted (or unmatched) we
        still produce a result; the service falls back to a generic
        prompt and a ``status="success"`` payload with ``fields={}`` and
        a warning explaining the fallback.
        """
        result = HyperExtractResult(document_id=document_id)
        result.enabled = self.is_enabled()
        if not result.enabled:
            result.status = "disabled"
            return result.to_dict()

        if not self._base_url or not self._model:
            result.status = "failed"
            result.error_message = (
                "hyperextract is enabled but HYPEREXTRACT_BASE_URL and/or "
                "HYPEREXTRACT_MODEL are not configured"
            )
            logger.warning(
                "hyperextract: %s (document_id=%s)",
                result.error_message,
                document_id,
            )
            result.warnings.append(result.error_message)
            return result.to_dict()

        resolved_type = (document_type or settings.hyperextract_default_type or "").strip().lower() or None
        result.document_type = resolved_type
        result.provider = self._provider_name
        result.model = self._model

        template = load_template(resolved_type)
        return self._run_extraction(result=result, text=text or "", metadata=metadata, template=template)

    def extract_invoice(
        self,
        document_id: str | int,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.extract_from_text(document_id, text, "factura", metadata=metadata)

    def extract_delivery_note(
        self,
        document_id: str | int,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.extract_from_text(document_id, text, "albaran", metadata=metadata)

    def extract_contract(
        self,
        document_id: str | int,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.extract_from_text(document_id, text, "contrato", metadata=metadata)

    def extract_quote(
        self,
        document_id: str | int,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.extract_from_text(document_id, text, "presupuesto", metadata=metadata)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run_extraction(
        self,
        *,
        result: HyperExtractResult,
        text: str,
        metadata: dict[str, Any] | None,
        template: HyperExtractTemplate | None,
    ) -> dict[str, Any]:
        if template is None and result.document_type:
            result.warnings.append(
                f"no template available for document_type={result.document_type!r}; "
                "falling back to a generic extraction prompt"
            )
        prompt_user = self._build_user_prompt(
            text=text,
            metadata=metadata,
            template=template,
        )
        prompt_system = self._build_system_prompt(template=template)

        started = time.perf_counter()
        try:
            raw = self._call_provider(prompt_system=prompt_system, prompt_user=prompt_user)
        except Exception as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            result.latency_ms = latency_ms
            result.status = "failed"
            # Do NOT include the full exception message — it can echo
            # the URL or the truncated request body. Log the detail at
            # WARNING level on the server side and return a generic
            # public-facing reason.
            logger.warning(
                "hyperextract: provider call failed (document_id=%s, type=%s, latency_ms=%s): %s",
                result.document_id,
                result.document_type,
                latency_ms,
                exc,
            )
            result.error_message = f"provider_call_failed: {type(exc).__name__}"
            result.warnings.append("provider_call_failed")
            return result.to_dict()

        latency_ms = int((time.perf_counter() - started) * 1000)
        result.latency_ms = latency_ms

        parsed = self._extract_json(raw)
        if parsed is None:
            result.status = "failed"
            result.error_message = "provider_returned_invalid_json"
            result.warnings.append("provider_returned_invalid_json")
            if self._persist_raw_output:
                result.raw_output = {"_raw": raw[:4000]}
            return result.to_dict()

        result.fields = self._coerce_dict(parsed.get("fields"))
        result.entities = self._coerce_list(parsed.get("entities"))
        result.relations = self._coerce_list(parsed.get("relations"))
        if isinstance(parsed.get("warnings"), list):
            for entry in parsed["warnings"]:
                if entry is None:
                    continue
                result.warnings.append(str(entry))
        if self._persist_raw_output:
            result.raw_output = {"_raw": raw[:4000]}
        result.status = "success"
        return result.to_dict()

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    @staticmethod
    def _build_system_prompt(template: HyperExtractTemplate | None) -> str:
        base = (
            "Eres un asistente que extrae información estructurada de "
            "documentos en español. Devuelve EXCLUSIVAMENTE JSON válido "
            "(sin ```json, sin texto alrededor). Si un campo no aparece, "
            "devuelve null. No inventes datos: si dudas, devuelve null y "
            "añade el campo al array 'warnings'."
        )
        if template and template.system_prompt:
            return f"{base}\n\n{template.system_prompt.strip()}"
        return base

    @staticmethod
    def _build_user_prompt(
        *,
        text: str,
        metadata: dict[str, Any] | None,
        template: HyperExtractTemplate | None,
    ) -> str:
        # Cap the payload to avoid hitting provider context windows on
        # very long OCR runs. 32k characters is comfortably above the
        # "the invoice page" use case; operators that need more can
        # raise ``hyperextract_timeout_seconds`` and split upstream.
        max_chars = 32_000
        truncated = len(text) > max_chars
        body = text if not truncated else text[:max_chars]
        header_lines: list[str] = []
        if metadata:
            document_type = metadata.get("document_type")
            if document_type:
                header_lines.append(f"Tipo de documento: {document_type}")
            filename = metadata.get("filename")
            if filename:
                header_lines.append(f"Nombre del fichero: {filename}")
            page_count = metadata.get("page_count")
            if page_count is not None:
                header_lines.append(f"Número de páginas: {page_count}")
            language = metadata.get("language")
            if language:
                header_lines.append(f"Idioma: {language}")
        field_instructions = build_field_instructions(template)
        sections: list[str] = []
        if header_lines:
            sections.append("Metadatos del documento:\n" + "\n".join(header_lines))
        if field_instructions:
            sections.append(field_instructions)
        sections.append(
            "Devuelve un objeto JSON con esta forma exacta:\n"
            '{"fields": {...}, "entities": [...], "relations": [...], "warnings": [...]}'
        )
        sections.append("Texto del documento:\n" + body)
        if truncated:
            sections.append(
                f"\n[Nota: el texto original tiene {len(text)} caracteres y fue "
                "truncado por el servicio a "
                f"{max_chars} caracteres.]"
            )
        return "\n\n".join(sections)

    # ------------------------------------------------------------------
    # Provider I/O
    # ------------------------------------------------------------------

    def _call_provider(self, *, prompt_system: str, prompt_user: str) -> str:
        """POST to the OpenAI-compatible chat-completions endpoint.

        Returns the assistant message text. Raises on transport errors
        or non-2xx HTTP status; the caller converts those into a typed
        failure result.
        """
        url = f"{self._base_url}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        payload = {
            "model": self._model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": prompt_system},
                {"role": "user", "content": prompt_user},
            ],
        }
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(url, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            # Log the exception type only; the message can include the
            # URL or sanitised headers and we never want to leak the
            # base URL into the public error envelope.
            raise RuntimeError(f"transport error: {type(exc).__name__}") from exc

        if response.status_code >= 400:
            # Body is intentionally not forwarded; providers sometimes
            # echo auth headers. Operators should look at server logs.
            raise RuntimeError(
                f"provider returned HTTP {response.status_code} {type(response).__name__}"
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError("provider returned non-JSON body") from exc

        message = (
            (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
            if isinstance(data, dict)
            else ""
        )
        if not isinstance(message, str) or not message.strip():
            raise RuntimeError("provider returned an empty assistant message")
        return message

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    _JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)
    _JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)

    @classmethod
    def _extract_json(cls, raw: str) -> dict[str, Any] | None:
        """Pull the first JSON object out of the provider response.

        Tries three strategies in order: a fenced `````json`` block, the
        first balanced ``{...}`` substring, and finally a full
        ``json.loads`` of the trimmed text. Returns ``None`` when none
        of them succeed.
        """
        if not raw:
            return None
        # 1) Fenced JSON.
        match = cls._JSON_FENCE_RE.search(raw)
        if match:
            candidate = match.group(1).strip()
            try:
                value = json.loads(candidate)
            except json.JSONDecodeError:
                value = None
            if isinstance(value, dict):
                return value
        # 2) First balanced object.
        match = cls._JSON_OBJECT_RE.search(raw)
        if match:
            candidate = match.group(0)
            try:
                value = json.loads(candidate)
            except json.JSONDecodeError:
                value = None
            if isinstance(value, dict):
                return value
        # 3) Whole payload.
        try:
            value = json.loads(raw.strip())
        except json.JSONDecodeError:
            return None
        return value if isinstance(value, dict) else None

    @staticmethod
    def _coerce_dict(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        out: dict[str, Any] = {}
        for key, item in value.items():
            out[str(key)] = item
        return out

    @staticmethod
    def _coerce_list(value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, list):
            return list(value)
        if isinstance(value, dict):
            return [value]
        return [value]


# ---------------------------------------------------------------------------
# Convenience singleton (lazy)
# ---------------------------------------------------------------------------


_default_service: HyperExtractService | None = None


def get_hyperextract_service() -> HyperExtractService:
    """Return a process-wide default service.

    The service is stateless apart from configuration; a single
    instance per worker is fine. Tests can construct their own with
    explicit arguments.
    """
    global _default_service
    if _default_service is None:
        _default_service = HyperExtractService()
    return _default_service
