"""R1 — Query transformation for the hybrid retriever.

The retriever was embedding the user query verbatim and ranking
chunks by cosine similarity. That works for short, well-formed
queries (``"último pedido del proveedor García"``) but suffers when
the user query is terse (``"presupuesto Garcia 245745"``) or
domain-specific (``"NIF B12345678"``). The vector space built from
document chunks is tuned to long, descriptive prose; a 3-token
user query lands in a sparse region of the space and the top-k
hits are noisy.

Two techniques help:

* **HyDE** (Hypothetical Document Embeddings, Gao et al. 2022) —
  ask the LLM to *generate* a hypothetical passage that would
  answer the question, then embed that passage and use it as the
  query. The generated passage is in the same vector space as the
  document chunks, so the cosine match is much tighter. Works
  best for natural-language questions.

* **Multi-query** (Wang et al. 2023) — ask the LLM to produce 3
  rephrasings of the query, embed each, and fuse the resulting
  retrieval lists with RRF. Works best for terse or ambiguous
  queries where one phrasing is not enough.

The module exposes a single :func:`transform_query` function that
returns a :class:`QueryTransformation` dataclass. The caller
(:func:`app.services.search_service.search_hybrid`) decides whether
to feed the transformed queries to the cosine branch, the BM25
branch, both, or none.

Both techniques require the LLM. The transformer is **fail-safe**:
when the LLM is misconfigured, the network is down, or the
response is unparseable, the function returns the original query
unchanged and records a Prometheus failure event. The retrieval
that depends on it still works — the cosine branch uses the
original query embedding, just with less recall than it would
have had with HyDE.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field

from app.core.config import settings
from app.services.metrics import track_query_transform

logger = logging.getLogger("app.services.query_transformer")


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class QueryTransformation:
    """The result of transforming a user query for retrieval.

    Attributes:
        original_query: the user query, unchanged.
        transformed_queries: the list of queries to feed the
            retriever. Always contains the original query as the
            first element so a caller that ignores the field and
            uses ``transformed_queries[0]`` gets something
            sensible. Subsequent entries are the LLM-generated
            reformulations (or the HyDE hypothetical).
        method: ``"hyde"``, ``"multi_query"``, ``"auto"`` (resolved
            by the transformer based on query shape), or
            ``"off"`` (no transformation attempted; the original
            query is the only entry).
        outcome: ``"success"`` when the LLM returned a parseable
            result, ``"fallback"`` when the LLM was unavailable or
            the response was unparseable, ``"disabled"`` when the
            transformer was off.
    """

    original_query: str
    transformed_queries: list[str] = field(default_factory=list)
    method: str = "off"
    outcome: str = "disabled"

    def __post_init__(self) -> None:
        if not self.transformed_queries:
            object.__setattr__(
                self,
                "transformed_queries",
                [self.original_query],
            )


# ---------------------------------------------------------------------------
# Method selection
# ---------------------------------------------------------------------------


# A query is "natural language" when it has 4+ words with at
# least one long word (>= 4 chars). Below that threshold the
# user is more likely typing a code or a short label, and
# multi-query works better than HyDE (which would just
# generate an awkward hypothetical).
_NL_WORD_COUNT = 4
_NL_LONG_WORD_LEN = 4


def auto_select_method(query: str) -> str:
    """Pick HyDE vs multi-query based on the query shape.

    Long natural-language question -> HyDE (the generated
    hypothetical is in the right embedding space).
    Short / code-like query -> multi-query (multiple reformulations
    catch different vocabularies).
    """
    words = query.split()
    long_word_count = sum(1 for w in words if len(w) >= _NL_LONG_WORD_LEN)
    if len(words) >= _NL_WORD_COUNT and long_word_count >= 1:
        return "hyde"
    return "multi_query"


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


_MULTI_QUERY_LINE_RE = re.compile(r"^\s*(?:\d+[\.)]\s*|[-*•]\s*)?(.+?)\s*$")


def _parse_multi_query_response(text: str, *, max_queries: int) -> list[str]:
    """Parse the LLM's response to a multi-query prompt.

    The LLM is asked to return one reformulation per line; we are
    forgiving about list markers (``1.``, ``-``, ``•``) and
    drop empty lines. We deduplicate case-insensitively and keep
    the original query out of the list — the caller adds it
    back via :class:`QueryTransformation.__post_init__`.
    """
    if not text:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in text.splitlines():
        match = _MULTI_QUERY_LINE_RE.match(raw)
        if not match:
            continue
        candidate = match.group(1).strip().strip('"').strip("'")
        if not candidate:
            continue
        key = candidate.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(candidate)
        if len(out) >= max_queries:
            break
    return out


def _parse_hyde_response(text: str) -> str:
    """The HyDE response is a free-form paragraph. We strip the
    most common LLM-induced framing (``Aquí tienes...``,
    ``Certainly!``) and return the rest as a single string. The
    caller is expected to embed it; we do not try to enforce a
    minimum length because a short LLM hallucination is still
    useful as a query vector.
    """
    if not text:
        return ""
    cleaned = text.strip()
    # Strip common "yes, here is..." preambles. We try the
    # *longest* match first so ``"Here is a passage: body"`` strips
    # the whole preamble rather than just ``"Here is"``.
    candidates = [
        "Aquí tienes el párrafo:",
        "Aquí tienes un párrafo",
        "Aquí tienes un parrafo",
        "Aquí tienes:",
        "Here is a passage:",
        "Here is the passage:",
        "Here is a paragraph:",
        "Here is the paragraph:",
        "Here is the text:",
        "Here is",
        "Here's the passage:",
        "Here's a passage:",
        "Here's a paragraph:",
        "Here's the paragraph:",
        "Here's the text:",
        "Here's",
        "Certainly!",
        "Sure!",
    ]
    lowered = cleaned.lower()
    for prefix in candidates:
        if lowered.startswith(prefix.lower()):
            cleaned = cleaned[len(prefix) :].lstrip(" :.-")
            break
    return cleaned.strip()


# ---------------------------------------------------------------------------
# LLM call (async)
# ---------------------------------------------------------------------------


_HYDE_SYSTEM_PROMPT = (
    "Eres un asistente documental. Te voy a dar una pregunta del "
    "usuario. Tu UNICA tarea es generar UN parrafo breve (maximo "
    "120 palabras) que PODRIA responder esa pregunta si el "
    "documento existiera. Escribe el parrafo como si fuera un "
    "fragmento literal del documento: usa el mismo registro, "
    "terminologia y nivel de detalle que un presupuesto, pedido, "
    "factura o plano tecnico real. NO respondas la pregunta, NO "
    "incluyas saludos, NO incluyas 'aqui tienes', SOLO el parrafo."
)

_HYDE_USER_TEMPLATE = (
    "Pregunta del usuario: {query}\n\nParrafo hipotetico del documento (maximo 120 palabras):"
)

_MULTI_QUERY_SYSTEM_PROMPT = (
    "Eres un asistente documental. Te voy a dar una pregunta del "
    "usuario. Tu UNICA tarea es generar EXACTAMENTE "
    "{n} reformulaciones alternativas de la pregunta, una por "
    "linea, sin numerar, sin comillas, sin explicaciones. Cada "
    "reformulacion debe conservar la intencion de la pregunta "
    "original pero usar palabras o angulos distintos. NO "
    "incluyas la pregunta original."
)

_MULTI_QUERY_USER_TEMPLATE = "Pregunta original: {query}\n\nReformulaciones ({n} lineas):"


async def _call_llm_for_hyde(query: str) -> str | None:
    """Ask the LLM to generate a hypothetical passage. Returns
    ``None`` on any failure (caller falls back to the original
    query)."""
    from app.ai.local_client import LocalOpenAICompatibleClient

    if not settings.ai_base_url or not settings.ai_model:
        return None
    try:
        client = LocalOpenAICompatibleClient()
        messages = [
            {"role": "system", "content": _HYDE_SYSTEM_PROMPT},
            {"role": "user", "content": _HYDE_USER_TEMPLATE.format(query=query)},
        ]
        return await client.chat(messages, temperature=0.0, max_tokens=200)
    except Exception as exc:  # pragma: no cover
        logger.warning("HyDE LLM call failed: %s", exc)
        return None


async def _call_llm_for_multi_query(query: str, n: int) -> list[str]:
    """Ask the LLM to produce ``n`` reformulations. Returns the
    parsed list (possibly empty) on any failure."""
    from app.ai.local_client import LocalOpenAICompatibleClient

    if not settings.ai_base_url or not settings.ai_model:
        return []
    try:
        client = LocalOpenAICompatibleClient()
        messages = [
            {"role": "system", "content": _MULTI_QUERY_SYSTEM_PROMPT.format(n=n)},
            {"role": "user", "content": _MULTI_QUERY_USER_TEMPLATE.format(query=query, n=n)},
        ]
        response = await client.chat(messages, temperature=0.3, max_tokens=400)
        return _parse_multi_query_response(response, max_queries=n)
    except Exception as exc:  # pragma: no cover
        logger.warning("Multi-query LLM call failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Synchronous wrapper (callers run inside the FastAPI request loop
# but the transformer is exposed as a sync function for ergonomics).
# ---------------------------------------------------------------------------


def transform_query(
    query: str,
    *,
    method: str | None = None,
    max_queries: int | None = None,
) -> QueryTransformation:
    """Transform ``query`` into a list of retrieval-friendly
    queries. Synchronous wrapper around the async LLM calls.

    Args:
        query: the user's search text.
        method: one of ``"hyde"``, ``"multi_query"``, ``"auto"``,
            ``"off"``. ``None`` reads
            ``settings.search_query_transform_strategy``.
        max_queries: cap on the number of reformulations. ``None``
            reads ``settings.search_query_transform_max_queries``.

    Returns:
        A :class:`QueryTransformation`. The ``transformed_queries``
        list always starts with the original query. On a failed
        LLM call the list contains only the original query and
        the ``outcome`` is ``"fallback"``.
    """
    normalised = (query or "").strip()
    if not normalised:
        return QueryTransformation(
            original_query=query or "",
            transformed_queries=[],
            method="off",
            outcome="disabled",
        )

    effective_method = (method or settings.search_query_transform_strategy or "off").lower()
    if effective_method not in {"hyde", "multi_query", "auto", "off"}:
        effective_method = "off"

    if effective_method == "off" or not settings.search_use_query_transformer:
        track_query_transform(effective_method, "disabled", latency_ms=0)
        return QueryTransformation(
            original_query=normalised,
            transformed_queries=[normalised],
            method=effective_method,
            outcome="disabled",
        )

    if effective_method == "auto":
        effective_method = auto_select_method(normalised)

    cap = max(1, int(max_queries or settings.search_query_transform_max_queries))

    start = time.perf_counter()
    try:
        if effective_method == "hyde":
            hypothetical = asyncio.run(_call_llm_for_hyde(normalised))
            latency_ms = int((time.perf_counter() - start) * 1000)
            if not hypothetical:
                track_query_transform("hyde", "fallback", latency_ms=latency_ms)
                return QueryTransformation(
                    original_query=normalised,
                    transformed_queries=[normalised],
                    method="hyde",
                    outcome="fallback",
                )
            cleaned = _parse_hyde_response(hypothetical)
            if not cleaned:
                track_query_transform("hyde", "fallback", latency_ms=latency_ms)
                return QueryTransformation(
                    original_query=normalised,
                    transformed_queries=[normalised],
                    method="hyde",
                    outcome="fallback",
                )
            track_query_transform("hyde", "success", latency_ms=latency_ms)
            return QueryTransformation(
                original_query=normalised,
                transformed_queries=[normalised, cleaned],
                method="hyde",
                outcome="success",
            )

        # multi_query
        reformulations = asyncio.run(_call_llm_for_multi_query(normalised, cap))
        latency_ms = int((time.perf_counter() - start) * 1000)
        if not reformulations:
            track_query_transform("multi_query", "fallback", latency_ms=latency_ms)
            return QueryTransformation(
                original_query=normalised,
                transformed_queries=[normalised],
                method="multi_query",
                outcome="fallback",
            )
        track_query_transform("multi_query", "success", latency_ms=latency_ms)
        # Original first, then the LLM's reformulations.
        return QueryTransformation(
            original_query=normalised,
            transformed_queries=[normalised, *reformulations],
            method="multi_query",
            outcome="success",
        )
    except Exception as exc:  # pragma: no cover
        latency_ms = int((time.perf_counter() - start) * 1000)
        logger.warning("Query transformer failed unexpectedly: %s", exc)
        track_query_transform(effective_method, "fallback", latency_ms=latency_ms)
        return QueryTransformation(
            original_query=normalised,
            transformed_queries=[normalised],
            method=effective_method,
            outcome="fallback",
        )


__all__ = [
    "QueryTransformation",
    "transform_query",
    "auto_select_method",
]
