"""Multi-query expansion for improved RAG recall.

Generates N query variations from the original question so the
search can retrieve documents that the raw query would miss.
The variations are cheap to generate (template-based, no LLM call)
and are fused via RRF with the original query results.

Why this helps:
- User asks "cuánto facturó Garcia en mayo" but the document says
  "importe total proveedor Garcia SL periodo 05/2026". The template
  variations bridge that vocabulary gap.
- Short or ambiguous queries get expanded without LLM cost.

Design:
- Template-based: no LLM call, ~5ms overhead.
- Variations are de-duplicated against the original.
- Each variation gets its own search; results merged via RRF.
- Configurable: ``settings.search_multi_query_enabled`` (default True),
  ``settings.search_multi_query_max_variants`` (default 3).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.config import settings

# ---------------------------------------------------------------------------
# Synonym / rephrasing templates
# ---------------------------------------------------------------------------

# Each template transforms the query by prepending/appending keywords
# or rephrasing common Spanish patterns.  The list is ordered by
# specificity — later templates are more aggressive.
_TEMPLATES: list[str] = [
    # Light rephrasing
    "{query} detalles",
    "{query} información",
    # Entity-focused
    "documento sobre {query}",
    "datos de {query}",
    "resultado de {query}",
    # Alternative phrasings for business queries
    "importe {query}",
    "total {query}",
    "fecha {query}",
    "número {query}",
]


@dataclass(frozen=True)
class QueryVariation:
    """A single expanded query with a weight for RRF fusion."""

    text: str
    weight: float  # 1.0 = original, < 1.0 = variation


def generate_query_variations(
    original: str,
    max_variants: int | None = None,
) -> list[QueryVariation]:
    """Return the original query plus N variations.

    The original always comes first with weight 1.0. Variations
    have decreasing weights so they influence the ranking less.
    """
    limit = max_variants or settings.search_multi_query_max_variants or 3
    if not settings.search_multi_query_enabled:
        return [QueryVariation(text=original, weight=1.0)]

    normalised = original.strip()
    if not normalised:
        return []

    variations: list[QueryVariation] = [
        QueryVariation(text=normalised, weight=1.0)
    ]

    for template in _TEMPLATES:
        if len(variations) >= limit + 1:  # +1 for original
            break
        candidate = template.format(query=normalised)
        # Skip if identical to original or already generated
        if candidate.lower() == normalised.lower():
            continue
        if any(v.text.lower() == candidate.lower() for v in variations):
            continue
        # Skip variations that are longer than 2x the original
        # (too much noise for short queries)
        if len(candidate) > len(normalised) * 2.5:
            continue
        # Weight decreases with each variation
        weight = 1.0 / (1 + len(variations))
        variations.append(QueryVariation(text=candidate, weight=weight))

    return variations


def expand_numbered_query(query: str) -> list[QueryVariation]:
    """Handle queries with numbers (NIF, invoice numbers, etc.) by
    generating number-only and context-only variations.

    Example: "factura 2026/143" → ["2026/143", "factura 2026/143", "2026-143"]
    """
    variations: list[QueryVariation] = [
        QueryVariation(text=query, weight=1.0)
    ]

    # Extract numbers/codes from the query
    number_pattern = re.compile(r"\b([A-Z0-9][A-Z0-9./-]{2,})\b", re.IGNORECASE)
    numbers = number_pattern.findall(query)

    for num in numbers:
        # Number-only variation (high specificity)
        if num.lower() != query.lower() and num not in [v.text for v in variations]:
            variations.append(QueryVariation(text=num, weight=0.9))

        # Normalised variation (strip separators)
        normalised = re.sub(r"[\s\-_/]", "", num)
        if normalised != num and normalised not in [v.text for v in variations]:
            variations.append(QueryVariation(text=normalised, weight=0.85))

    return variations
