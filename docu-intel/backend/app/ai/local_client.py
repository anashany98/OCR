from __future__ import annotations

import asyncio
import base64
import contextlib
import io
import random
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.core.config import settings


@dataclass(frozen=True)
class LocalAIConfig:
    provider: str
    base_url: str
    model: str
    api_key_configured: bool


@dataclass(frozen=True)
class LocalVisionConfig:
    provider: str
    base_url: str
    model: str
    api_key_configured: bool


class LocalAICircuitOpen(RuntimeError):
    pass


class ContextSizeExceededError(RuntimeError):
    """The prompt exceeded the model's loaded context_length.

    Raised when the LLM server returns a 400 with a "context size" /
    "context length" message. This is a *caller* error (prompt too big),
    NOT a server fault: it must NOT open the circuit breaker, and the
    agent should retry with a smaller context budget rather than fail.
    """

    pass


def _looks_like_context_size_error(status_code: int, body: bytes) -> bool:
    """True when a 4xx response means 'prompt too long for the model'."""
    if status_code != 400:
        return False
    text = body.decode(errors="replace").lower()
    return "context size" in text or "context length" in text or "maximum context" in text


@dataclass
class _CircuitState:
    failures: int = 0
    opened_until: float = 0.0


_LOCAL_AI_CIRCUITS: dict[tuple[str, str], _CircuitState] = {}

# Concurrency limit: prevent too many simultaneous LLM calls from
# exhausting VRAM or causing OOM. With 15 concurrent users this
# keeps the LLM server responsive. Vision calls share the same
# semaphore because they compete for the same GPU memory.
_LLM_SEMAPHORE: asyncio.Semaphore | None = None


def _get_llm_semaphore() -> asyncio.Semaphore:
    global _LLM_SEMAPHORE
    if _LLM_SEMAPHORE is None:
        _LLM_SEMAPHORE = asyncio.Semaphore(
            settings.ai_max_concurrent_requests if settings.ai_max_concurrent_requests > 0 else 100
        )
    return _LLM_SEMAPHORE


def reset_local_ai_circuit_breakers() -> None:
    _LOCAL_AI_CIRCUITS.clear()


def get_local_ai_config() -> LocalAIConfig:
    return LocalAIConfig(
        provider=settings.ai_provider,
        base_url=settings.ai_base_url,
        model=settings.ai_model,
        api_key_configured=bool(settings.ai_api_key),
    )


def get_local_vision_config() -> LocalVisionConfig:
    return LocalVisionConfig(
        provider=settings.vision_provider,
        base_url=settings.vision_base_url,
        model=settings.vision_model,
        api_key_configured=bool(settings.vision_api_key),
    )


class LocalOpenAICompatibleClient:
    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        max_retries: int | None = None,
        retry_base_delay_seconds: float | None = None,
        circuit_breaker_failures: int | None = None,
        circuit_breaker_reset_seconds: float | None = None,
    ) -> None:
        self.base_url = (base_url or settings.ai_base_url).rstrip("/")
        self.model = model or settings.ai_model
        self.api_key = api_key if api_key is not None else settings.ai_api_key
        self.transport = transport
        self.max_retries = max(0, settings.ai_max_retries if max_retries is None else max_retries)
        self.retry_base_delay_seconds = max(
            0.0,
            settings.ai_retry_base_delay_seconds
            if retry_base_delay_seconds is None
            else retry_base_delay_seconds,
        )
        self.circuit_breaker_failures = max(
            1,
            settings.ai_circuit_breaker_failures
            if circuit_breaker_failures is None
            else circuit_breaker_failures,
        )
        self.circuit_breaker_reset_seconds = max(
            0.0,
            settings.ai_circuit_breaker_reset_seconds
            if circuit_breaker_reset_seconds is None
            else circuit_breaker_reset_seconds,
        )

    async def chat(
        self,
        messages: list[dict],
        temperature: float = 0.0,
        timeout: float | None = None,
        max_tokens: int = 4000,
    ) -> str:
        if not self.base_url or not self.model:
            raise RuntimeError("Local AI is not configured")
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        async with _get_llm_semaphore():
            payload = await self._post_chat_completion(
                headers=headers,
                timeout=timeout or settings.ai_request_timeout_seconds,
                json_payload={
                    "model": self.model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
        choices = payload.get("choices")
        if not choices or not isinstance(choices, list) or len(choices) == 0:
            raise ValueError(
                f"Malformed LLM response: 'choices' is empty or missing. "
                f"Model={self.model}"
            )
        message = choices[0].get("message")
        if not message or not isinstance(message, dict):
            raise ValueError(
                f"Malformed LLM response: 'message' is missing in first choice. "
                f"Model={self.model}"
            )
        content = message.get("content") or ""
        # Thinking models (qwen3-*) put the actual response in
        # reasoning_content while content stays empty.
        if not content.strip():
            content = message.get("reasoning_content") or ""
        if not content.strip():
            raise ValueError(
                f"Malformed LLM response: 'content' is empty in message. "
                f"Model={self.model}"
            )
        return content

    async def chat_stream(
        self,
        messages: list[dict],
        temperature: float = 0.0,
        timeout: float | None = None,
        max_tokens: int = 4000,
    ) -> AsyncIterator[str | tuple[str, str]]:
        """Yield text chunks as the LLM produces them.

        Yields one of:
          - str: a piece of the visible answer (delta.content)
          - ("thinking", str): a piece of the model's internal reasoning
            (delta.reasoning_content). The UI uses this to show a
            "razonando..." indicator before the answer starts streaming.
        """
        if not self.base_url or not self.model:
            raise RuntimeError("Local AI is not configured")
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        headers["Accept"] = "text/event-stream"
        request_timeout = timeout or settings.ai_request_timeout_seconds
        json_payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }

        # Retry-with-backoff, but only BEFORE the first token
        # lands in the caller's hands. Re-streaming a partial
        # answer would duplicate content in the UI, so the
        # retry stops as soon as the upstream server starts
        # sending SSE chunks. Transient errors during
        # stream setup (connection refused, 5xx, 429) still
        # get the full ``max_retries`` budget; errors raised
        # while we are already mid-stream propagate
        # immediately so the partial answer is preserved.
        last_exc: Exception | None = None
        async with _get_llm_semaphore():
            for attempt in range(self.max_retries + 1):
                self._raise_if_circuit_open()
                try:
                    async with (
                        httpx.AsyncClient(
                            timeout=httpx.Timeout(
                                connect=5.0,
                                read=request_timeout,
                                write=5.0,
                                pool=10.0,
                            ),
                            transport=self.transport,
                        ) as client,
                        client.stream(
                            "POST",
                            f"{self.base_url}/chat/completions",
                            headers=headers,
                            json=json_payload,
                        ) as response,
                    ):
                        if response.status_code >= 400:
                            import logging
                            _log = logging.getLogger("app.ai.local_client")
                            body = await response.aread()
                            _log.warning(
                                "LLM stream %s returned %s: %s",
                                self.model,
                                response.status_code,
                                body[:2000].decode(errors="replace"),
                            )
                            # A prompt-too-big error is a caller fault, not a
                            # server fault: do NOT record it as a circuit
                            # failure (which would otherwise cascade-fail
                            # every subsequent call for ~30s). Propagate a
                            # dedicated error the agent can retry with less
                            # context.
                            if _looks_like_context_size_error(response.status_code, body):
                                raise ContextSizeExceededError(
                                    f"Prompt exceeded the model's loaded context_length "
                                    f"for {self.model}"
                                )
                            response.raise_for_status()
                        self._record_success()
                        async for line in response.aiter_lines():
                            if not line:
                                continue
                            if line.startswith("data:"):
                                data = line[len("data:") :].strip()
                                if data == "[DONE]":
                                    break
                                try:
                                    import json

                                    payload = json.loads(data)
                                except Exception:
                                    continue
                                choices = payload.get("choices") or []
                                if not choices:
                                    continue
                                delta = (choices[0] or {}).get("delta") or {}
                                thinking = delta.get("reasoning_content")
                                if thinking:
                                    yield ("thinking", thinking)
                                piece = delta.get("content")
                                if piece:
                                    yield piece
                        return
                except Exception as exc:
                    last_exc = exc
                    # ContextSizeExceededError is a caller fault (prompt
                    # too big), NOT a server fault. Do NOT trip the circuit
                    # breaker — that would cascade-fail all subsequent calls.
                    if isinstance(exc, ContextSizeExceededError):
                        raise
                    if not _is_retryable_ai_error(exc) or attempt >= self.max_retries:
                        self._record_failure()
                        raise
                    await self._sleep_before_retry(attempt)
                    continue
            if last_exc is not None:
                self._record_failure()
                raise last_exc
            raise RuntimeError("chat_stream retry loop exited without an exception")

    async def _post_chat_completion(
        self,
        *,
        headers: dict[str, str],
        timeout: float,
        json_payload: dict,
    ) -> dict:
        self._raise_if_circuit_open()
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(
                        connect=5.0,
                        read=timeout,
                        write=5.0,
                        pool=10.0,
                    ),
                    transport=self.transport,
                ) as client:
                    response = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers=headers,
                        json=json_payload,
                    )
                    if response.status_code >= 400:
                        import logging
                        _log = logging.getLogger("app.ai.local_client")
                        _log.warning(
                            "LLM %s returned %s: %s",
                            self.model,
                            response.status_code,
                            response.text[:2000],
                        )
                        # Prompt-too-big is a caller fault, not a server fault:
                        # do NOT trip the circuit breaker (which would cascade-
                        # fail every call for ~30s). Raise a dedicated error so
                        # the agent can retry with a smaller context budget.
                        if _looks_like_context_size_error(
                            response.status_code, response.content
                        ):
                            raise ContextSizeExceededError(
                                f"Prompt exceeded the model's loaded context_length "
                                f"for {self.model}"
                            )
                    response.raise_for_status()
                    self._record_success()
                    return response.json()
            except Exception as exc:
                last_exc = exc
                # ContextSizeExceededError is a caller fault, not a server
                # fault — do NOT record a circuit breaker failure.
                if isinstance(exc, ContextSizeExceededError):
                    raise
                if attempt >= self.max_retries or not _is_retryable_ai_error(exc):
                    self._record_failure()
                    raise
                await self._sleep_before_retry(attempt)
        raise RuntimeError("AI request failed without an exception") from last_exc

    async def _sleep_before_retry(self, attempt: int) -> None:
        delay = self.retry_base_delay_seconds * (2**attempt)
        if delay <= 0:
            return
        jitter = random.uniform(0.0, delay * 0.25)
        await asyncio.sleep(delay + jitter)

    @property
    def _circuit_key(self) -> tuple[str, str]:
        return (self.base_url, self.model)

    def _state(self) -> _CircuitState:
        return _LOCAL_AI_CIRCUITS.setdefault(self._circuit_key, _CircuitState())

    def _raise_if_circuit_open(self) -> None:
        state = self._state()
        now = time.monotonic()
        if state.opened_until > now:
            raise LocalAICircuitOpen(
                f"Local AI temporarily unavailable for {self.model}; "
                f"circuit resets in {state.opened_until - now:.1f}s"
            )
        if state.opened_until and state.opened_until <= now:
            state.failures = 0
            state.opened_until = 0.0

    def _record_success(self) -> None:
        state = self._state()
        state.failures = 0
        state.opened_until = 0.0

    def _record_failure(self) -> None:
        state = self._state()
        state.failures += 1
        if state.failures >= self.circuit_breaker_failures:
            state.opened_until = time.monotonic() + self.circuit_breaker_reset_seconds


def _is_retryable_ai_error(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        return status_code == 429 or status_code >= 500
    return isinstance(exc, (httpx.TimeoutException, httpx.TransportError))


# ---------------------------------------------------------------------------
# Vision client — uses an OpenAI-compatible multimodal chat completion with
# `image_url` content blocks. Works with LM Studio, vLLM, llama.cpp,
# OpenRouter, OpenAI, Anthropic (via adapter) and any other provider that
# exposes /v1/chat/completions and supports vision.
# ---------------------------------------------------------------------------


class LocalVisionClient:
    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        use_structured_model: bool = False,
    ) -> None:
        self.base_url = (base_url or settings.vision_base_url or settings.ai_base_url).rstrip("/")
        # Some vision tasks (structured JSON output, plan room
        # suggestions) work much better with a non-thinking model:
        # the thinking variant spends the entire budget on chain-of-
        # thought and returns empty content.
        if model:
            self.model = model
        elif use_structured_model and settings.vision_model_structured:
            self.model = settings.vision_model_structured
        else:
            self.model = settings.vision_model
        self.api_key = (
            api_key if api_key is not None else (settings.vision_api_key or settings.ai_api_key)
        )
        self.max_retries = max(0, getattr(settings, "vision_max_retries", 2))
        self.retry_base_delay_seconds = 1.0

    def is_configured(self) -> bool:
        return bool(self.base_url and self.model)

    @staticmethod
    def _encode_data_url(path: Path) -> tuple[str, str]:
        """Return (data_url, mime_type) for a local image, downscaling if
        needed. LM Studio and most local servers reject huge images."""
        import imghdr

        mime, _ = ("image/jpeg", None)
        kind = imghdr.what(str(path))
        if kind == "png":
            mime = "image/png"
        elif kind in ("gif",):
            mime = "image/gif"
        elif kind in ("webp",):
            mime = "image/webp"
        else:
            mime = "image/jpeg"

        max_dim = settings.vision_max_image_dim
        try:
            from PIL import Image  # type: ignore

            with Image.open(path) as img:
                if max(img.size) > max_dim:
                    img.thumbnail((max_dim, max_dim))
                buf = io.BytesIO()
                fmt = "PNG" if mime == "image/png" else "JPEG"
                img.convert("RGB").save(buf, format=fmt, quality=85)
                encoded = base64.b64encode(buf.getvalue()).decode("ascii")
        except Exception:
            # Fallback: raw base64 of the file, no resizing.
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{encoded}", mime

    async def describe(
        self,
        image_path: Path,
        prompt: str = (
            "Describe esta imagen con precision y detalle en espanol. "
            "Incluye: tipo de documento (foto, plano, captura de pantalla, "
            "foto de producto, etc.), contenido visible (textos, numeros, "
            "datos clave), colores o elementos visuales destacables, y "
            "cualquier informacion util para entender de que va el documento. "
            "Si la imagen contiene texto, transcribelo literalmente. Si no "
            "puedes leer algo con claridad, indicalo en vez de inventarlo."
        ),
        timeout: float | None = None,
        max_tokens: int = 800,
    ) -> str:
        if not self.is_configured():
            raise RuntimeError("Vision model is not configured")
        if not image_path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")
        data_url, _ = self._encode_data_url(image_path)
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
            "temperature": 0.0,
            "max_tokens": max_tokens,
        }
        async with _get_llm_semaphore():
            last_exc: Exception | None = None
            for attempt in range(self.max_retries + 1):
                try:
                    async with httpx.AsyncClient(
                        timeout=httpx.Timeout(
                            connect=5.0,
                            read=timeout or settings.vision_timeout_seconds,
                            write=5.0,
                            pool=10.0,
                        ),
                    ) as client:
                        response = await client.post(
                            f"{self.base_url}/chat/completions",
                            headers=headers,
                            json=payload,
                        )
                        if response.status_code == 429 or response.status_code >= 500:
                            last_exc = httpx.HTTPStatusError(
                                f"Vision model returned {response.status_code}",
                                request=response.request,
                                response=response,
                            )
                            if attempt < self.max_retries:
                                await asyncio.sleep(self.retry_base_delay_seconds * (2 ** attempt))
                                continue
                        response.raise_for_status()
                        data = response.json()
                        msg = data["choices"][0]["message"]
                        # Thinking models (qwen3-vl-8b-thinking etc.) put
                        # the actual response in reasoning_content while
                        # content stays empty.  Fall back to content when
                        # reasoning_content is missing or empty.
                        answer = msg.get("content") or ""
                        if not answer.strip():
                            answer = msg.get("reasoning_content") or ""
                        return answer
                except httpx.HTTPStatusError:
                    raise
                except Exception as exc:
                    last_exc = exc
                    if attempt < self.max_retries:
                        await asyncio.sleep(self.retry_base_delay_seconds * (2 ** attempt))
                        continue
                    raise
            if last_exc is not None:
                raise last_exc
            raise RuntimeError("Vision model request failed without an exception")

    async def transcribe_table(
        self,
        image_path: Path,
        *,
        timeout: float | None = None,
    ) -> str:
        """Ask the vision model to transcribe a tabular region as a clean
        markdown table. Used for scanned PDFs and photos that PaddleOCR
        could not structure. Returns the markdown text, or raises on
        failure (caller catches and falls back)."""
        prompt = (
            "Observa esta imagen. Si contiene una tabla (presupuesto, "
            "factura, listado, planilla, etc.), transcribela como una "
            "tabla markdown EXACTA: una fila de cabecera con pipes `|`, "
            "una fila separadora `|---|`, y luego una fila por cada "
            "dato. Conserva los numeros, simbolos y textos tal cual. "
            "Si hay varias tablas, una tras otra separadas por una linea "
            "en blanco. Si NO hay tabla, responde un resumen estructurado "
            "del contenido visible en markdown. Responde SOLO con "
            "markdown, sin explicaciones, sin ``` alrededor. "
            "Idioma: espanol."
        )
        return await self.describe(
            image_path,
            prompt=prompt,
            timeout=timeout or (settings.vision_timeout_seconds * 1.5),
            max_tokens=2000,
        )

    async def transcribe_table_from_pdf_page(
        self,
        pdf_path: Path,
        page_index: int,
        *,
        output_dir: Path | None = None,
        timeout: float | None = None,
    ) -> str:
        """Render a specific PDF page to a PNG and ask the vision model
        to transcribe the table. Used as a recovery path when the text
        pipeline (PyMuPDF + pdfplumber) returns no structured table."""
        from tempfile import NamedTemporaryFile

        import fitz  # PyMuPDF

        # Render the page at higher zoom for better OCR of small text.
        zoom = 2.0
        with fitz.open(pdf_path) as pdf:
            if page_index >= len(pdf):
                raise ValueError(f"page {page_index} out of range for {pdf_path}")
            page = pdf[page_index]
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            if output_dir is not None:
                output_dir.mkdir(parents=True, exist_ok=True)
                tmp = output_dir / f"vision_page_{page_index + 1}.png"
                pix.save(str(tmp))
            else:
                with NamedTemporaryFile(suffix=".png", delete=False) as tmp_file:
                    pix.save(tmp_file.name)
                tmp = Path(tmp_file.name)
        try:
            return await self.transcribe_table(tmp, timeout=timeout)
        finally:
            if output_dir is None and tmp.exists():
                with contextlib.suppress(Exception):
                    tmp.unlink()
