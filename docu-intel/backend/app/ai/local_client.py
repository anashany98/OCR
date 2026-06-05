from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator

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
    def __init__(self, base_url: str | None = None, model: str | None = None, api_key: str | None = None) -> None:
        self.base_url = (base_url or settings.ai_base_url).rstrip("/")
        self.model = model or settings.ai_model
        self.api_key = api_key if api_key is not None else settings.ai_api_key

    async def chat(self, messages: list[dict], temperature: float = 0.0, timeout: float = 120.0, max_tokens: int = 2000) -> str:
        if not self.base_url or not self.model:
            raise RuntimeError("Local AI is not configured")
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
            response.raise_for_status()
            payload = response.json()
            return payload["choices"][0]["message"]["content"]

    async def chat_stream(
        self,
        messages: list[dict],
        temperature: float = 0.0,
        timeout: float = 120.0,
        max_tokens: int = 2000,
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
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers=headers,
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "stream": True,
                },
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    if line.startswith("data:"):
                        data = line[len("data:"):].strip()
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
                        # Qwen3 (and other reasoning models) stream their
                        # internal reasoning in `reasoning_content`. We
                        # surface it as a separate event so the UI can
                        # show "razonando..." while the model is thinking.
                        thinking = delta.get("reasoning_content")
                        if thinking:
                            yield ("thinking", thinking)
                        piece = delta.get("content")
                        if piece:
                            yield piece


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
            api_key
            if api_key is not None
            else (settings.vision_api_key or settings.ai_api_key)
        )

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
        async with httpx.AsyncClient(timeout=timeout or settings.vision_timeout_seconds) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]

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
        import fitz  # PyMuPDF
        from tempfile import NamedTemporaryFile

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
                tmp = Path(NamedTemporaryFile(suffix=".png", delete=False).name)
                pix.save(str(tmp))
        try:
            return await self.transcribe_table(tmp, timeout=timeout)
        finally:
            if output_dir is None and tmp.exists():
                try:
                    tmp.unlink()
                except Exception:
                    pass
