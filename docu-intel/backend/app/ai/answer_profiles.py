"""Bounded context and output budgets for chat intent classes."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class AnswerProfile:
    name: str
    context_tokens: int
    max_output_tokens: int


_PROFILES = {
    "exact": AnswerProfile("exact", 1200, 256),
    "factual": AnswerProfile("factual", 2500, 500),
    "summary": AnswerProfile("summary", 4000, 900),
    "synthesis": AnswerProfile("synthesis", 6000, 1800),
}
_EXACT_REFERENCE = re.compile(r"\b[A-Za-z0-9]+[-_/][A-Za-z0-9_-]+\b|\.[A-Za-z0-9]{2,5}\b")
_SYNTHESIS_MARKERS = ("compara", "comparar", "diferencia", "analiza", "explica", "relacion")
_SUMMARY_MARKERS = ("resume", "resumen", "sintetiza", "detalla")


def select_answer_profile(question: str) -> AnswerProfile:
    normalized = question.lower().strip()
    if _EXACT_REFERENCE.search(question):
        return _PROFILES["exact"]
    if any(marker in normalized for marker in _SYNTHESIS_MARKERS):
        return _PROFILES["synthesis"]
    if any(marker in normalized for marker in _SUMMARY_MARKERS):
        return _PROFILES["summary"]
    return _PROFILES["factual"]
