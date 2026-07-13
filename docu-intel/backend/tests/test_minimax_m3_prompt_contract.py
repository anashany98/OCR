"""Deterministic prompt and abstention contract tests."""
from __future__ import annotations

from app.ai.context import build_grounded_response
from app.ai.prompts import _build_system_prompt


def test_prompt_requires_canonical_abstention_phrase():
    prompt = _build_system_prompt(enable_thinking=False)
    assert "No dispongo de esa informacion en los documentos procesados." in prompt


def test_grounded_fallback_uses_an_explicit_abstention_marker():
    response = build_grounded_response(
        question="Cual es la proxima auditoria fiscal?",
        context_items=[],
        warnings=[],
    )
    assert response.confidence == 0.0
    assert "No he encontrado informacion" in response.answer
