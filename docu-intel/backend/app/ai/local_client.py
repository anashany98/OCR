from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.core.config import settings


@dataclass(frozen=True)
class LocalAIConfig:
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


class LocalOpenAICompatibleClient:
    def __init__(self, base_url: str | None = None, model: str | None = None, api_key: str | None = None) -> None:
        self.base_url = (base_url or settings.ai_base_url).rstrip("/")
        self.model = model or settings.ai_model
        self.api_key = api_key if api_key is not None else settings.ai_api_key

    async def chat(self, messages: list[dict], temperature: float = 0.0, timeout: float = 20.0) -> str:
        if not self.base_url or not self.model:
            raise RuntimeError("Local AI is not configured")
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json={"model": self.model, "messages": messages, "temperature": temperature},
            )
            response.raise_for_status()
            payload = response.json()
            return payload["choices"][0]["message"]["content"]
