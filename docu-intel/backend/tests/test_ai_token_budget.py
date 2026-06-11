"""M11 (Sprint 4): Tests for AI context token budget clipping.

Verifies that ``build_context_text`` respects
``settings.ai_max_context_tokens`` by greedily including context
items until the token budget is exhausted.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.ai.context import ContextItem
from app.ai.prompts import (
    _PROMPT_OVERHEAD_TOKENS,
    _TOKENS_PER_WORD,
    _estimate_tokens,
    build_context_text,
)


def _make_item(summary: str, *, score: float = 1.0, filename: str = "doc.pdf") -> ContextItem:
    return ContextItem(
        title="test",
        summary=summary,
        document_id=1,
        document_filename=filename,
        page_number=1,
        relevance_score=score,
        excerpt=summary,
        confidence=0.9,
        ocr_confidence=0.85,
        source_path="presupuestos/12345/doc.pdf",
    )


# ---------------------------------------------------------------------------
# _estimate_tokens
# ---------------------------------------------------------------------------


class TestEstimateTokens:
    def test_empty_string(self):
        assert _estimate_tokens("") == 0

    def test_single_word(self):
        assert _estimate_tokens("hello") == int(1 * _TOKENS_PER_WORD)

    def test_multiple_words(self):
        assert _estimate_tokens("hello world foo bar") == int(4 * _TOKENS_PER_WORD)

    def test_whitespace_only(self):
        # split() on whitespace returns empty list
        assert _estimate_tokens("   ") == 0

    def test_newlines_counted_as_separators(self):
        # "a\nb\nc" splits to ["a", "b", "c"] = 3 words
        assert _estimate_tokens("a\nb\nc") == int(3 * _TOKENS_PER_WORD)


# ---------------------------------------------------------------------------
# build_context_text with token budget
# ---------------------------------------------------------------------------


class TestBuildContextTextTokenBudget:
    def test_no_budget_includes_all_items(self):
        """When ai_max_context_tokens is 0 (disabled), all items are included."""
        items = [_make_item(f"word " * 20) for _ in range(5)]
        with patch("app.ai.prompts.settings") as mock_settings:
            mock_settings.ai_max_context_tokens = 0
            mock_settings.prompt_injection_action = "flag"
            mock_settings.prompt_injection_use_xml_wrap = False
            result = build_context_text(items)
        # All 5 items should be present
        assert result.count("Fuente=") == 5

    def test_budget_clips_later_items(self):
        """Items beyond the token budget are dropped."""
        # Create items with known sizes; each item is roughly
        # "word " × 200 ≈ 200 words ≈ 260 tokens per line
        items = [_make_item(f"word " * 200, score=1.0 - i * 0.1) for i in range(10)]
        # Budget: overhead + room for only ~3 items (3 × 260 = 780 tokens)
        budget = _PROMPT_OVERHEAD_TOKENS + 800
        with patch("app.ai.prompts.settings") as mock_settings:
            mock_settings.ai_max_context_tokens = budget
            mock_settings.prompt_injection_action = "flag"
            mock_settings.prompt_injection_use_xml_wrap = False
            result = build_context_text(items)
        lines_with_source = result.count("Fuente=")
        assert lines_with_source < 10
        assert lines_with_source >= 1

    def test_budget_zero_items_fit(self):
        """When budget is too small for even one item, zero items are included."""
        items = [_make_item("x " * 500)]
        # Budget = overhead only, no room for context
        budget = _PROMPT_OVERHEAD_TOKENS + 10
        with patch("app.ai.prompts.settings") as mock_settings:
            mock_settings.ai_max_context_tokens = budget
            mock_settings.prompt_injection_action = "flag"
            mock_settings.prompt_injection_use_xml_wrap = False
            result = build_context_text(items)
        assert result == ""

    def test_empty_items_returns_empty(self):
        with patch("app.ai.prompts.settings") as mock_settings:
            mock_settings.ai_max_context_tokens = 6000
            mock_settings.prompt_injection_action = "flag"
            mock_settings.prompt_injection_use_xml_wrap = False
            result = build_context_text([])
        assert result == ""

    def test_budget_none_uses_attribute_default(self):
        """When settings object lacks the attribute, getattr default kicks in."""
        items = [_make_item("short text")]
        with patch("app.ai.prompts.settings") as mock_settings:
            # Remove the attribute so getattr falls back to 0
            del mock_settings.ai_max_context_tokens
            mock_settings.prompt_injection_action = "flag"
            mock_settings.prompt_injection_use_xml_wrap = False
            result = build_context_text(items)
        # Without a budget, all items are included
        assert "Fuente=" in result
