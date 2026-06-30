from __future__ import annotations

import asyncio
import base64
import json
import logging
import threading
from pathlib import Path
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger("app.ai.nuextract_client")

_semaphore: threading.BoundedSemaphore | None = None
_semaphore_limit: int | None = None
_semaphore_lock = threading.Lock()


class NuExtractError(RuntimeError):
    """Raised when the NuExtract3 provider call fails or returns unusable data."""


def _get_nuextract_semaphore() -> threading.BoundedSemaphore:
    global _semaphore, _semaphore_limit
    limit = max(1, int(settings.nuextract_max_concurrency or 1))
    if _semaphore is not None and _semaphore_limit == limit:
        return _semaphore
    with _semaphore_lock:
        if _semaphore is None or _semaphore_limit != limit:
            _semaphore = threading.BoundedSemaphore(limit)
            _semaphore_limit = limit
    return _semaphore


def run_async_blocking(coro):
    """Run an async NuExtract call from sync OCR / service code."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: dict[str, Any] = {}
    error: dict[str, BaseException] = {}

    def _runner() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except BaseException as exc:  # noqa: BLE001 - propagate across thread boundary
            error["exc"] = exc

    thread = threading.Thread(target=_runner, daemon=False)
    thread.start()
    thread.join()
    if error:
        raise error["exc"]
    return result.get("value")


class NuExtractClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
        api_key: str | None = None,
    ) -> None:
        self.base_url = (base_url if base_url is not None else settings.nuextract_base_url).rstrip("/")
        self.model = model if model is not None else settings.nuextract_model
        self.timeout_seconds = float(
            timeout_seconds
            if timeout_seconds is not None
            else settings.nuextract_timeout_seconds
        )
        self.api_key = api_key

    def is_configured(self) -> bool:
        return bool(settings.nuextract_enabled and self.base_url and self.model)

    async def markdown_from_image(self, image_path: str | Path) -> str:
        payload = self.build_markdown_payload(image_path)
        data = await self._post(payload)
        text = self._assistant_text(data)
        if not text:
            raise NuExtractError("nuextract returned empty markdown")
        return text

    async def extract_from_image(
        self,
        image_path: str | Path,
        template: dict[str, Any],
    ) -> dict[str, Any]:
        payload = self.build_extraction_payload(image_path, template)
        data = await self._post(payload)
        text = self._assistant_text(data)
        if not text:
            raise NuExtractError("nuextract returned empty extraction")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise NuExtractError("nuextract returned invalid JSON") from exc
        if not isinstance(parsed, dict):
            raise NuExtractError("nuextract JSON response is not an object")
        return parsed

    def build_markdown_payload(self, image_path: str | Path) -> dict[str, Any]:
        return {
            "model": self.model,
            "temperature": settings.nuextract_markdown_temperature,
            "messages": [self._image_message(image_path)],
            "chat_template_kwargs": {
                "mode": "markdown",
                "enable_thinking": settings.nuextract_enable_thinking,
            },
        }

    def build_extraction_payload(
        self,
        image_path: str | Path,
        template: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "model": self.model,
            "temperature": settings.nuextract_extraction_temperature,
            "messages": [self._image_message(image_path)],
            "chat_template_kwargs": {
                "template": json.dumps(template, indent=4, ensure_ascii=False),
                "enable_thinking": settings.nuextract_enable_thinking,
            },
        }

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.base_url or not self.model:
            raise NuExtractError("nuextract base URL or model is not configured")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        url = f"{self.base_url}/chat/completions"
        semaphore = _get_nuextract_semaphore()
        try:
            await asyncio.to_thread(semaphore.acquire)
            try:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    response = await client.post(url, headers=headers, json=payload)
                    response.raise_for_status()
                    data = response.json()
            finally:
                semaphore.release()
        except httpx.HTTPError as exc:
            logger.warning("nuextract HTTP call failed: %s", type(exc).__name__)
            raise NuExtractError(f"nuextract HTTP call failed: {type(exc).__name__}") from exc
        except ValueError as exc:
            logger.warning("nuextract returned non-JSON response")
            raise NuExtractError("nuextract returned non-JSON response") from exc
        if not isinstance(data, dict):
            raise NuExtractError("nuextract response is not an object")
        return data

    def _image_message(self, image_path: str | Path) -> dict[str, Any]:
        encoded = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
        return {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{encoded}"},
                }
            ],
        }

    @staticmethod
    def _assistant_text(data: dict[str, Any]) -> str:
        try:
            choices = data.get("choices") or []
            message = choices[0].get("message") or {}
            return str(message.get("content") or "").strip()
        except (AttributeError, IndexError, TypeError):
            return str(data.get("text") or data.get("content") or "").strip()


__all__ = ["NuExtractClient", "NuExtractError", "run_async_blocking"]
