"""Local AI answer generation: one-shot LLM call with context.

Extracted from agent.py to keep the orchestrator under 800 lines.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import httpx

from app.ai.context import ContextItem
from app.core.config import settings

logger = logging.getLogger("app.ai.local_answer")


async def try_local_ai_answer(
    question: str,
    context_items: list[ContextItem],
    warnings: list[str],
    *,
    fallback: str,
    model: str | None = None,
    client_factory: Callable[[], Any] | None = None,
) -> str | None:
    """One-shot LLM call with the same context as the streaming
    path. Returns the model's answer, or ``fallback`` (and logs
    why) when the LLM is misconfigured, fails validation, or
    fabricates documents.
    """
    from app.ai.local_client import ContextSizeExceededError, LocalOpenAICompatibleClient
    from app.ai.prompts import build_ai_messages, build_context_text
    from app.ai.validation import (
        question_is_spanish,
        response_fabricates_documents,
        response_looks_spanish,
    )

    selected_model = model or settings.ai_model
    if not settings.ai_base_url or not selected_model:
        return None

    context_text = build_context_text(context_items)
    warning_text = "\n".join(warnings) if warnings else "Sin advertencias previas."
    messages = build_ai_messages(question, context_text, warning_text)
    client = client_factory() if client_factory else LocalOpenAICompatibleClient(model=selected_model)
    try:
        answer = await client.chat(messages, temperature=0.0)
    except ContextSizeExceededError:
        halved = max(1000, (settings.ai_max_context_tokens or 6000) // 2)
        logger.warning("Prompt exceeded context_length — retry budget=%d: %s", halved, question[:100])
        messages = build_ai_messages(
            question, build_context_text(context_items, max_tokens_override=halved), warning_text
        )
        try:
            answer = await client.chat(messages, temperature=0.0)
        except Exception as exc:
            logger.warning("Context-shrunk retry failed: %s", exc)
            answer = ""
    except TimeoutError:
        logger.warning("AI answer timed out for question: %s", question[:100])
        return None
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        logger.warning("AI client request failed: %s - question: %s", exc, question[:100])
        return None
    except Exception as exc:
        logger.error(
            "Unexpected error in AI answer generation: %s - question: %s", exc, question[:100]
        )
        return None

    if not answer and "qwen" in selected_model.lower():
        logger.warning(
            "Qwen3 returned an empty answer (0 tokens) with /no_think — "
            "retrying once with thinking enabled for question: %s",
            question[:100],
        )
        retry_messages = build_ai_messages(
            question, context_text, warning_text, enable_thinking=True
        )
        try:
            answer = await client.chat(retry_messages, temperature=0.0)
        except Exception as exc:
            logger.warning("Qwen3 thinking-enabled retry failed: %s", exc)
            answer = ""

    if not answer:
        return fallback
    if question_is_spanish(question) and not response_looks_spanish(answer):
        logger.warning("AI response not in Spanish for Spanish question: %s", answer[:200])
        return fallback
    if response_fabricates_documents(answer, context_items):
        logger.warning("AI response mentions documents not in context: %s", answer[:200])
        return fallback
    return _polish_answer_text(answer)


def _polish_answer_text(answer: str) -> str:
    """Minimal cleanup of model output."""
    if not answer:
        return answer
    import re
    # Remove markdown headers that LLMs sometimes add
    answer = re.sub(r"^#{1,3}\s+", "", answer, flags=re.MULTILINE)
    # Some OpenAI-compatible local servers leak the streaming terminator
    # into a non-streaming response. It is protocol metadata, never answer
    # content, and may be attached directly to the final word.
    answer = re.sub(r"\s*\[DONE\]\s*$", "", answer, flags=re.IGNORECASE)
    return answer.strip()
