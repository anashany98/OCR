"""Small, deterministic model router for chat latency."""
from __future__ import annotations

from dataclasses import dataclass

from app.ai.answer_profiles import select_answer_profile
from app.core.config import settings


@dataclass(frozen=True)
class ChatModelRoute:
    model: str
    profile: str
    context_tokens: int
    max_output_tokens: int

    @property
    def cache_key(self) -> str:
        return f"{self.model}:{self.profile}"


_DEEP_REASONING_MARKERS = frozenset(
    {
        "compara",
        "comparar",
        "diferencia",
        "analiza",
        "explica",
        "por que",
        "porque",
        "relacion",
        "resume",
        "resumen",
    }
)


def select_chat_model(question: str) -> ChatModelRoute:
    """Select the fast model only for small factual requests.

    The router is intentionally conservative: any lengthy or synthesis-like
    question remains on the primary model. If no fast model is configured, it
    is a no-op and therefore safe to enable before provisioning a second model.
    """
    primary = settings.ai_model
    normalized = question.lower().strip()
    answer_profile = select_answer_profile(question)
    is_simple = (
        len(normalized) <= 140
        and not any(marker in normalized for marker in _DEEP_REASONING_MARKERS)
    )
    if settings.ai_model_routing_enabled and settings.ai_fast_model and is_simple:
        return ChatModelRoute(
            model=settings.ai_fast_model,
            profile=answer_profile.name,
            context_tokens=answer_profile.context_tokens,
            max_output_tokens=answer_profile.max_output_tokens,
        )
    return ChatModelRoute(
        model=primary,
        profile=answer_profile.name,
        context_tokens=answer_profile.context_tokens,
        max_output_tokens=answer_profile.max_output_tokens,
    )
