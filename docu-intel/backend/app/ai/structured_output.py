"""Structured output formatting for AI responses.

Converts free-text LLM responses into structured JSON that the
frontend can render as tables, charts, or formatted cards.

Why this matters:
- Raw LLM text is hard to parse for display
- Structured output enables programmatic verification
- Sources/confidence are explicit, not buried in prose
- Frontend can render data visualizations from the JSON

Design:
- Post-processing layer (no LLM call needed)
- Extracts sources, confidence, and key data from the response
- Falls back to plain text if parsing fails
- Schema v1: simple enough for all document types
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from typing import Any

from app.core.config import settings


@dataclass
class StructuredResponse:
    """Structured representation of an AI answer."""

    answer: str
    confidence: float = 0.0
    sources: list[SourceRef] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    format: str = "text"  # text | table | chart | card

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


@dataclass
class SourceRef:
    """Reference to a source document/page."""

    document_id: int | None = None
    document_filename: str | None = None
    page_number: int | None = None
    relevance: float = 0.0
    excerpt: str | None = None


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------

def _extract_numbers(text: str) -> list[float]:
    """Extract monetary/numeric values from text.

    Handles both ES format (1.234,56) and EN format (1,234.56).
    """
    patterns = [
        # Currency symbol: 1.234,56 € or 1,234.56 EUR
        r"(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,2})?)\s*(?:€|EUR|USD|\$)",
        # Labeled values: Total: 1.234,56 or IVA: 892,50
        r"(?:total|importe|suma|base|iva|monto)[:\s]*(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,2})?)",
        # With currency word: 1.234,56 euros
        r"(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,2})?)\s*(?:euros?|dolares?)",
        # Standalone ES format with comma decimal: 666,24 or 1.156,24
        r"\b(\d{1,3}(?:\.\d{3})*,\d{1,2})\b",
        # Standalone EN format: 666.24 or 1156.24
        r"\b(\d{1,3}(?:,\d{3})*\.\d{1,2})\b",
    ]
    numbers = []
    seen = set()
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            try:
                raw = match.group(1)
                # Parse ES format: dots are thousands, comma is decimal
                if "," in raw and "." in raw:
                    if raw.rindex(",") > raw.rindex("."):
                        # ES: 1.234,56
                        val = float(raw.replace(".", "").replace(",", "."))
                    else:
                        # EN: 1,234.56
                        val = float(raw.replace(",", ""))
                elif "," in raw:
                    # Could be ES decimal (666,24) or EN thousands (1,234)
                    parts = raw.split(",")
                    if len(parts) == 2 and len(parts[1]) <= 2:
                        # ES decimal: 666,24
                        val = float(raw.replace(",", "."))
                    else:
                        # EN thousands: 1,234
                        val = float(raw.replace(",", ""))
                elif "." in raw:
                    # Could be ES thousands (1.234) or EN decimal (666.24)
                    parts = raw.split(".")
                    if all(p.isdigit() and len(p) == 3 for p in parts):
                        # ES thousands: 1.234
                        val = float(raw.replace(".", ""))
                    else:
                        # EN decimal or ambiguous
                        val = float(raw)
                else:
                    val = float(raw)
                # Deduplicate
                if val not in seen and val > 0:
                    seen.add(val)
                    numbers.append(val)
            except (ValueError, AttributeError):
                continue
    return numbers


def _extract_dates(text: str) -> list[str]:
    """Extract date references from text."""
    patterns = [
        r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
        r"(\d{4}[/-]\d{1,2}[/-]\d{1,2})",
        r"(?:fecha|date)[:\s]*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
    ]
    dates = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            dates.append(match.group(1))
    return dates


def _extract_references(text: str) -> list[str]:
    """Extract document references (invoice numbers, order numbers, etc.)."""
    patterns = [
        r"(?:factura|albarán|albaran|pedido|presupuesto|nº|no\.?|ref\.?)\s*[:#-]?\s*([A-Z0-9][A-Z0-9./-]{2,})",
        r"\b([A-Z]{1,4}[\-_]?\d{2,4}[\-_]?\d{1,6})\b",
    ]
    refs = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            ref = match.group(1) if match.lastindex else match.group(0)
            if ref not in refs:
                refs.append(ref)
    return refs


def _detect_format(text: str) -> str:
    """Detect the best format for the response."""
    # Check for tabular data
    if "|" in text and text.count("|") >= 4:
        return "table"
    # Check for numerical summary
    numbers = _extract_numbers(text)
    if len(numbers) >= 2:
        return "card"
    return "text"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def to_structured_response(
    answer: str,
    context_items: list[Any] | None = None,
    warnings: list[str] | None = None,
) -> StructuredResponse:
    """Convert a free-text answer to a StructuredResponse.

    This is a post-processing step — no LLM call. It extracts
    metadata from the text and context to enrich the response.
    """
    if not answer or not answer.strip():
        return StructuredResponse(
            answer="",
            confidence=0.0,
            warnings=["empty_response"],
        )

    # Extract structured data from the text
    numbers = _extract_numbers(answer)
    dates = _extract_dates(answer)
    refs = _extract_references(answer)

    # Build data payload
    data: dict[str, Any] = {}
    if numbers:
        data["amounts"] = numbers
        if len(numbers) == 1:
            data["amount"] = numbers[0]
        elif len(numbers) >= 2:
            data["total"] = numbers[0]
            data["breakdown"] = numbers[1:]
    if dates:
        data["dates"] = dates
    if refs:
        data["references"] = refs

    # Build source references from context items
    sources: list[SourceRef] = []
    if context_items:
        seen_docs: set[int] = set()
        for item in context_items:
            if hasattr(item, "document_id") and item.document_id:
                if item.document_id not in seen_docs:
                    seen_docs.add(item.document_id)
                    sources.append(SourceRef(
                        document_id=item.document_id,
                        document_filename=getattr(item, "document_filename", None),
                        page_number=getattr(item, "page_number", None),
                        relevance=getattr(item, "relevance_score", 0.0),
                        excerpt=(item.summary[:200] if hasattr(item, "summary") else None),
                    ))

    # Calculate confidence based on source quality
    confidence = 0.5  # default
    if sources:
        avg_relevance = sum(s.relevance for s in sources) / len(sources)
        confidence = min(0.95, 0.3 + avg_relevance * 0.5)
    if numbers:
        confidence = min(0.95, confidence + 0.1)  # numeric answers are more precise

    # Detect format
    fmt = _detect_format(answer)

    # Merge warnings
    all_warnings = list(warnings or [])

    return StructuredResponse(
        answer=answer.strip(),
        confidence=round(confidence, 2),
        sources=sources,
        data=data,
        warnings=all_warnings,
        format=fmt,
    )
