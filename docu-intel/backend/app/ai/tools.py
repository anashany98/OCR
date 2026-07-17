"""Tool selection and classification helpers for the AI agent.

This module owns the **decision of which backend tool(s) to call**
for a given user question. It does not call the tools — that is
the orchestrator's job (see ``app.ai.context.collect_context``).

The classifier is intentionally rule-based rather than ML. We have
a fixed tool surface (15 internal tools) and a small, well-known
question grammar ("dame el presupuesto N", "cuanto nos hemos gastado
en X"). Rules are easier to test, easier to extend, and they fail
loudly when a new question type is not covered (vs. a model that
silently picks the wrong tool).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from app.core.config import settings

# Re-exported so other code in the project that imports
# ``app.ai.agent._money_filters`` still works (this is the alias the
# original agent.py used).
from app.tools.internal import _money_filters  # noqa: F401

# ---------------------------------------------------------------------------
# Multi-language intent lexicon (AI-007)
# ---------------------------------------------------------------------------
# The previous classifier hardcoded Spanish keywords (``presupuest``,
# ``pedido``, ``factura`` …) which meant that questions in English,
# French, German, Italian or Portuguese always fell through to the
# generic ``hybrid_search`` fallback instead of being routed to the
# dedicated structured tools (``aggregate_business``,
# ``get_budget_by_number``, …).
#
# The lexicon below maps each *concept* the agent can act on to the
# surface forms that mean the same thing across the working
# languages of the platform. Every entry has been pre-normalised
# (lowercased, accents stripped) so the matcher can do cheap
# substring checks after ``_normalize``.
#
# Adding a new language for an existing concept is a one-line change
# here. Adding a new concept is a new key in the dict plus a
# consumer in :func:`select_tools_for_question`.


_BUDGET_HINTS: frozenset[str] = frozenset(
    {
        # Spanish
        "presupuesto",
        "presupuestos",
        "cotizacion",
        "cotizaciones",
        "oferta",
        "ofertas",
        "estimacion",
        "estimaciones",
        # English
        "budget",
        "budgets",
        "quote",
        "quotes",
        "quotation",
        "quotations",
        "estimate",
        "estimates",
        "bid",
        "bids",
        # French
        "devis",
        # German
        "angebot",
        "kostenvoranschlag",
        # Italian
        "preventivo",
        "preventivi",
        "offerta",
        "offerte",
        # Portuguese
        "orcamento",
        "orcamentos",
        "cotacao",
        "cotacoes",
        "proposta",
    }
)

_ORDER_HINTS: frozenset[str] = frozenset(
    {
        # Spanish
        "pedido",
        "pedidos",
        "orden de compra",
        "ordenes de compra",
        # English (the bare ``po`` is intentionally absent because
        # the two-letter token is too short and would match inside
        # unrelated words like ``pour`` / ``polo``.)
        "order",
        "orders",
        "purchase order",
        "purchase orders",
        # French
        "commande",
        "commandes",
        "bon de commande",
        # German
        "bestellung",
        "bestellungen",
        "auftrag",
        "auftraege",
        # Italian
        "ordine",
        "ordini",
        "ordine di acquisto",
        # Portuguese
        "ordem de compra",
        "encomenda",
        "encomendas",
    }
)

_INVOICE_HINTS: frozenset[str] = frozenset(
    {
        # Spanish (lemma + plural + past participle for "facturado")
        "factura",
        "facturas",
        "facturad",
        "recibo",
        "recibos",
        # English
        "invoice",
        "invoices",
        "invoiced",
        "bill",
        "bills",
        "receipt",
        "receipts",
        # French
        "facture",
        "factures",
        "facturee",
        "recu",
        "reception",
        # German
        "rechnung",
        "rechnungen",
        "quittung",
        "quittungen",
        # Italian
        "fattura",
        "fatture",
        "ricevuta",
        "ricevute",
        "fatturat",
        # Portuguese
        "fatura",
        "faturas",
        "conta",
        "contas",
    }
)

_PLAN_HINTS: frozenset[str] = frozenset(
    {
        # Spanish
        "plano",
        "planos",
        "planta",
        "plantas",
        "croquis",
        # English
        "plan",
        "plans",
        "floor plan",
        "floor plans",
        "blueprint",
        "blueprints",
        "drawing",
        "drawings",
        "layout",
        "layouts",
        # French
        # German
        "plaene",
        "grundriss",
        "grundrisse",
        "zeichnung",
        # Italian
        "pianta",
        "piante",
        "disegno",
        "disegni",
        # Portuguese
        "desenho",
        "desenhos",
    }
)

_AGGREGATION_HINTS: frozenset[str] = frozenset(
    {
        # Spanish (lemma + plural + common variants)
        "cuanto",
        "cuanta",
        "cuantos",
        "cuantas",
        "total",
        "suma",
        "importe",
        "gastado",
        "gastados",
        "cobrado",
        "cobrados",
        "promedio",
        "media",
        # English
        "how much",
        "how many",
        "sum",
        "amount",
        "spent",
        "invoiced",
        "collected",
        "average",
        "avg",
        "mean",
        "tally",
        # French
        "combien",
        "montant",
        "somme",
        "moyenne",
        # German
        "wieviel",
        "gesamt",
        "summe",
        "betrag",
        "durchschnitt",
        # Italian
        "quanto",
        "quanti",
        "quante",
        "totale",
        "somma",
        "importo",
        # Portuguese
        "quantos",
        "quantas",
        "soma",
        "faturado",
        # Ranking hints (cross-language)
        "top",
        "ranking",
        "rank",
        "principales",
        "mayor",
        "menor",
        "mas alto",
        "mas altos",
        "mas baja",
        "mas bajas",
        "mas grande",
        "mas grandes",
        "highest",
        "largest",
        "biggest",
        "lowest",
        "smallest",
        "le plus",
        "le moins",
        "hoechste",
        "niedrigste",
        "piu alto",
        "piu basso",
        "mais alto",
        "mais baixo",
    }
)

_ACCEPTED_WITHOUT_ORDER_HINTS: frozenset[str] = frozenset(
    {
        # Spanish
        "aceptados sin pedido",
        "aceptadas sin pedido",
        "sin pedido",
        "no tienen pedido",
        "sin orden",
        # English
        "accepted without order",
        "approved without po",
        "approved without purchase order",
        "accepted without purchase order",
        "without purchase order",
        "missing purchase order",
        "missing po",
        "no order",
        "no purchase order",
        # French
        "acceptes sans commande",
        "sans commande",
        # German
        "akzeptiert ohne bestellung",
        "ohne bestellung",
        # Italian
        "accettati senza ordine",
        "senza ordine",
        # Portuguese
        "aceites sem pedido",
        "sem pedido",
    }
)

_DUPLICATE_HINTS: frozenset[str] = frozenset(
    {
        "duplicado",
        "duplicados",
        "duplicada",
        "duplicadas",
        "duplicate",
        "duplicates",
        "duplicated",
        "doublon",
        "doublons",
        "doppel",
        "doppelt",
        "duplicato",
        "duplicati",
        "duplicata",
    }
)

_LOW_OCR_HINTS: frozenset[str] = frozenset(
    {
        "baja confianza",
        "baja calidad",
        "error ocr",
        "errores ocr",
        "ocr bajo",
        "confianza ocr",
        "revisar ocr",
        "ocr dudoso",
        "low confidence",
        "low quality",
        "ocr error",
        "ocr errors",
        "bad ocr",
        "poor ocr",
        "review ocr",
        "faible confiance",
        "erreur ocr",
        "niedrige qualitaet",
        "ocr fehler",
        "bassa qualita",
        "errore ocr",
        "baixa qualidade",
        "erro ocr",
    }
)

# Room lexicon: alias -> canonical name. The first entry wins for
# any given alias string so that English "kitchen" is mapped to
# the canonical "kitchen" rather than to the Spanish "cocina".
# Multi-word aliases ("salle de bain", "living room") are placed
# before their shorter stems so the matcher does not return the
# stem's canonical ("bedroom") when the longer phrase is present.
_ROOM_HINTS: dict[str, str] = {
    # English (multi-word first to avoid ``room`` shadowing ``living room``)
    "living room": "living_room",
    "lounge": "living_room",
    "sitting": "living_room",
    "kitchen": "kitchen",
    "kitchens": "kitchen",
    "bedroom": "bedroom",
    "bedrooms": "bedroom",
    "rooms": "bedroom",
    "room": "bedroom",
    "bathroom": "bathroom",
    "bathrooms": "bathroom",
    "toilet": "bathroom",
    "toilets": "bathroom",
    "wc": "bathroom",
    "corridor": "corridor",
    "corridors": "corridor",
    "hallway": "corridor",
    # Spanish
    "salon": "salon",
    "salones": "salon",
    "sala": "salon",
    "cocina": "cocina",
    "cocinas": "cocina",
    "dormitorio": "dormitorio",
    "dormitorios": "dormitorio",
    "habitacion": "dormitorio",
    "habitaciones": "dormitorio",
    "cuarto": "dormitorio",
    "cuartos": "dormitorio",
    "recamara": "dormitorio",
    "recamaras": "dormitorio",
    "bano": "bano",
    "banos": "bano",
    "banio": "bano",
    "banios": "bano",
    "aseo": "bano",
    "aseos": "bano",
    "pasillo": "pasillo",
    "pasillos": "pasillo",
    "vestibulo": "pasillo",
    "comedor": "comedor",
    "comedores": "comedor",
    "terraza": "terraza",
    "terrazas": "terraza",
    "garaje": "garaje",
    "garajes": "garaje",
    "garage": "garaje",
    "recibidor": "recibidor",
    "recibidores": "recibidor",
    "hall": "recibidor",
    "entrada": "recibidor",
    # Italian
    "soggiorno": "soggiorno",
    "salotto": "soggiorno",
    "camera": "camera",
    "camere": "camera",
    "stanza": "camera",
    "stanze": "camera",
    "bagno": "bagno",
    "bagni": "bagno",
    "corridoio": "corridoio",
    "corridoi": "corridoio",
    "cucina": "cucina",
    # Portuguese
    "quarto": "quarto",
    "quartos": "quarto",
    "cozinha": "cozinha",
    "banheiro": "banheiro",
    # French
    "sejour": "salon",
    "chambre": "chambre",
    "chambres": "chambre",
    "cuisine": "cuisine",
    "salle de bain": "salle_de_bain",
    "salle de bains": "salle_de_bain",
    "salle d eau": "salle_de_bain",
}


def _contains_word(normalized: str, word: str) -> bool:
    """Return True if ``word`` appears in ``normalized`` as a whole
    word or as a stem of a longer inflected form.

    For single-word stems we accept any trailing letters (so
    ``facturad`` matches ``facturado`` and ``invoice`` matches
    ``invoices``) but we still require a word boundary on the
    left so the stem cannot fire in the middle of an unrelated
    token (e.g. ``expedido`` would not match ``pedido``). For
    multi-word hints ("low confidence", "purchase order") we use
    a phrase-level match that requires the hint to start and end
    at word boundaries.
    """
    if " " in word or "-" in word:
        # Multi-word hints: require the phrase to start at a word
        # boundary (start of string or preceded by whitespace) and
        # end at one (end of string or followed by whitespace/punct).
        pattern = r"(?:^|\s)" + re.escape(word) + r"(?=\s|$|[.,;:?!])"
        return re.search(pattern, normalized) is not None
    # ``[\w]*`` after the stem absorbs inflections (``facturado``,
    # ``invoices``, ``pedidos``) but the leading ``(?<![\w])`` keeps
    # the stem from firing inside an unrelated token.
    return re.search(rf"(?<![\w]){re.escape(word)}[\w]*(?![\w])", normalized) is not None


def _contains_any(normalized: str, words: Iterable[str]) -> bool:
    """Return True if any of ``words`` appears in ``normalized`` as a
    whole word. Replaces naive ``in`` substring checks that used to
    match "pedido" inside "expedido"."""
    return any(_contains_word(normalized, word) for word in words)


_CAD_QUESTION_PROPERTIES: frozenset[str] = frozenset(
    {
        "medida",
        "medidas",
        "cota",
        "cotas",
        "dimension",
        "dimensiones",
        "entidad",
        "entidades",
        "elemento",
        "elementos",
        "capa",
        "capas",
        "unidad",
        "unidades",
        "aparece",
        "aparecen",
        "donde",
        "ubicacion",
        "dudosa",
        "dudoso",
    }
)
_CAD_IDENTIFIER_QUESTION_RE = re.compile(
    r"\b[A-Z]{1,8}\d+(?:\s*-\s*[A-Z]{1,8}\d+)*\b", re.IGNORECASE
)


def _looks_like_cad_question(normalized: str, mentioned_filenames: list[str]) -> bool:
    """Detect CAD intent without requiring the literal word ``plano``.

    Labels such as ``M1``/``M4`` and questions about drawing units are
    common after the user already opened a plan, so routing them through
    hybrid search loses the structured native evidence.
    """
    has_property = _contains_any(normalized, _CAD_QUESTION_PROPERTIES)
    if not has_property:
        return False
    has_cad_filename = any(name.lower().endswith((".dxf", ".dwg")) for name in mentioned_filenames)
    has_plan_hint = (
        _contains_any(normalized, _PLAN_HINTS) or "dxf" in normalized or "dwg" in normalized
    )
    has_identifier = _CAD_IDENTIFIER_QUESTION_RE.search(normalized) is not None
    has_drawing_hint = _contains_any(
        normalized, ("dibujo", "esquema", "drawing", "zeichnung", "disegno")
    )
    has_native_dimension_signal = _contains_any(normalized, ("cota", "cotas")) and _contains_any(
        normalized, ("unidad", "unidades", "dudosa", "dudoso")
    )
    return (
        has_cad_filename
        or has_plan_hint
        or has_identifier
        or has_drawing_hint
        or has_native_dimension_signal
    )


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolCall:
    """A single tool call the orchestrator should execute.

    ``name`` is one of the tool identifiers registered in
    ``app.tools.internal`` (e.g. ``hybrid_search``,
    ``get_budget_by_number``, ``aggregate_business``).

    ``arguments`` is a free-form dict whose shape is documented
    in the tool's implementation. We keep this typed as ``dict``
    rather than per-tool TypedDict because the surface keeps
    growing and a single schema would be a maintenance hazard.
    """

    name: str
    arguments: dict[str, Any]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def select_tools_for_question(
    question: str,
    *,
    active_context: Any | None = None,
) -> list[ToolCall]:
    """Pick the right set of internal tools for ``question``.

    Returns a list because some question types (a budget number +
    a fuzzy content match) legitimately need more than one tool
    chained. The list is ordered: tools earlier in the list are
    expected to be the primary source of context; later tools
    are fallback / enrichment.

    The decision tree:

    1. **Aggregation** ("cuanto", "total", "suma", "facturado" ...)
       -> ``aggregate_business`` + ``hybrid_search`` (for citations).
    2. **Filename mention** -> ``find_document_by_filename`` +
       placeholder slots for full details and related docs (the
       orchestrator rewrites the placeholders after the lookup).
    3. **Document number** + entity type -> ``get_budget_by_number``
       / ``get_order_by_number`` + same placeholders.
    4. **Catch-all patterns** ("presupuestos aceptados sin pedido",
       "ultimo pedido", "duplicados", "baja confianza", entities,
       plan rooms, planos in general) -> single-tool call.
    5. **Fallback** -> ``hybrid_search`` with whatever relevance
       filters we can infer from the question (supplier, client,
       amount range).
    """
    # A resolved follow-up contains a ``[Contexto: ...]`` prefix.  It is
    # useful to the answer model, but must not be mistaken for a new user
    # identifier (for example the active document database id).
    routing_question = _strip_context_prefix(question)
    normalized = _normalize(routing_question)
    document_number = _extract_document_number(routing_question)
    document_numbers = _extract_document_numbers(routing_question)
    literal_identifiers = _extract_literal_identifiers(routing_question)
    exact_subjects = extract_exact_subject_phrases(routing_question)
    mentioned_filenames = _extract_filenames(routing_question)

    # A CAD filename is authoritative.  Drawing filenames often contain
    # words such as "medidas" or "salon"; if the room-measurement branch
    # sees those first it mistakes the filename for a room question and
    # discards the native CAD evidence entirely.
    if (
        settings.cad_chat_tools_enabled
        and mentioned_filenames
        and any(name.casefold().endswith((".dxf", ".dwg")) for name in mentioned_filenames)
    ):
        return [
            ToolCall("find_document_by_filename", {"query": mentioned_filenames[0]}),
            ToolCall("get_document_full_details", {"document_id": 0}),
            ToolCall("get_plan_cad_context", {"query": mentioned_filenames[0]}),
        ]

    # ---- Plan measurements ----
    # "Cuanto mide el salon" contains an aggregation hint ("cuanto"),
    # but it is not a business aggregate. Route room measurements before
    # SQL-style budget/order/invoice aggregation.
    if _contains_any(
        normalized,
        (
            "mide",
            "medida",
            "medidas",
            "superficie",
            "tamano",
            "how big",
            "how large",
            "size",
            "area",
            "square",
            "taille",
            "dimension",
            "groesse",
            "flaeche",
            "dimensione",
            "superficie",
            "tamanho",
            "surface",
        ),
    ) and (room_name := _extract_room_name(normalized)):
        return [ToolCall("search_plan_room_measurements", {"room_name": room_name})]

    # Native CAD context has priority for generic plan questions. It exposes
    # DIMENSION entities, layers, inserts and provenance instead of relying on
    # OCR chunks that often flatten a drawing into an ungrounded summary.
    if settings.cad_chat_tools_enabled and _looks_like_cad_question(
        normalized,
        mentioned_filenames,
    ):
        if mentioned_filenames:
            return [
                ToolCall("find_document_by_filename", {"query": mentioned_filenames[0]}),
                ToolCall("get_document_full_details", {"document_id": 0}),
                ToolCall("get_plan_cad_context", {"query": mentioned_filenames[0]}),
            ]
        return [ToolCall("get_plan_cad_context", {"query": routing_question})]

    # ---- Presupuesto / pedido / factura by number ----
    # Keep this before generic aggregation so "importe del presupuesto
    # 260009" resolves the specific budget instead of returning a global
    # total over every budget.
    if (
        document_number
        and not any(
            document_number in identifier and len(identifier) > len(document_number)
            for identifier in literal_identifiers
        )
        and (
            _contains_any(normalized, _BUDGET_HINTS)
            or _contains_any(normalized, _ORDER_HINTS)
            or _contains_any(normalized, _INVOICE_HINTS)
            or "documento" in normalized
            or "document" in normalized
            or "commande" in normalized
        )
    ):
        if _contains_any(normalized, _BUDGET_HINTS):
            primary = ToolCall("get_budget_by_number", {"budget_number": document_number})
        elif _contains_any(normalized, _ORDER_HINTS):
            primary = ToolCall("get_order_by_number", {"order_number": document_number})
        else:
            primary = ToolCall("get_budget_by_number", {"budget_number": document_number})
        tools = [
            primary,
            ToolCall("get_document_full_details", {"document_id": 0}),
            ToolCall("get_related_documents", {"document_id": 0}),
        ]
        if not settings.search_exact_first_enabled:
            tools.append(ToolCall("hybrid_search", {"query": question, "filters": {"limit": 6}}))
        return tools

    # A bare 5-7 digit identifier is common in document chat.  It used to
    # fall into semantic retrieval, where nearby documents could outrank the
    # actual identifier.  Search every supplied number exactly and let the
    # collector report ambiguity instead of guessing.
    if document_numbers:
        tools = [
            ToolCall("find_document_by_exact_identifier", {"number": number, "kind": "generic"})
            for number in document_numbers
        ]
        if not settings.search_exact_first_enabled:
            tools.append(ToolCall("hybrid_search", {"query": question, "filters": {"limit": 6}}))
        return tools

    # References, tax ids and prefixed invoice/order codes are identifiers as
    # well, even when they are not plain numbers.  Literal retrieval provides
    # the same corpus-wide, non-fuzzy guarantee for these forms.
    if literal_identifiers:
        return [
            ToolCall("find_documents_by_exact_phrase", {"phrase": identifier})
            for identifier in literal_identifiers
        ]

    # Visual follow-ups must stay inside the active document set and operate
    # on image-backed pages, not on whichever OCR chunk mentions "imagen"
    # first. With no active set, use the same visual-page route globally.
    visual_hints = (
        "imagen",
        "imagenes",
        "foto",
        "fotos",
        "visual",
        "describe",
        "describeme",
        "que se ve",
    )
    if _contains_any(normalized, visual_hints):
        last_document_ids = list(getattr(active_context, "last_retrieved_document_ids", []) or [])
        if last_document_ids:
            return [
                ToolCall(
                    "get_documents_by_ids",
                    {
                        "document_ids": last_document_ids[:12],
                        "visual_only": True,
                    },
                )
            ]
        if exact_subjects:
            return [
                ToolCall(
                    "find_documents_by_exact_phrase",
                    {"phrase": phrase, "visual_only": True},
                )
                for phrase in exact_subjects
            ]
        return [
            ToolCall(
                "search_visual_documents",
                {"query": routing_question, "limit": 12},
            )
        ]

    # Named subjects are not limited to one document type.  A person, client,
    # supplier, project, property or a quoted label must be found by its
    # literal spelling across the whole corpus before semantic similarity is
    # allowed to answer.  This avoids conflating names that only look alike.
    if exact_subjects:
        return [
            ToolCall("find_documents_by_exact_phrase", {"phrase": phrase})
            for phrase in exact_subjects
        ]

    # Conversation follow-up: when the previous turn retrieved several
    # documents and the user now asks for a property (number, date, amount,
    # supplier, invoice, details), search those documents directly before
    # falling back to the whole corpus. This is what makes turns such as
    # ``que presupuestos tiene ese hostal?`` -> ``necesito el numero`` stay
    # on the same project instead of returning unrelated budgets.
    last_document_ids = list(getattr(active_context, "last_retrieved_document_ids", []) or [])
    followup_property_hints = (
        "numero",
        "nº",
        "num",
        "fecha",
        "importe",
        "precio",
        "coste",
        "total",
        "detalle",
        "detalles",
        "presupuesto",
        "pedido",
        "factura",
        "proveedor",
        "cliente",
        "pendiente",
        "pagar",
        "pago",
        "linea",
        "lineas",
        "albaran",
        "paga",
        "pagado",
        "factura que",
        "que sabes",
        "que mas",
        "mas detalles",
    )
    global_followup_hints = ("todos", "global", "compara", "cada", "entre proyectos")
    if (
        last_document_ids
        and _contains_any(normalized, followup_property_hints)
        and not _contains_any(normalized, global_followup_hints)
    ):
        return [
            ToolCall(
                "get_documents_by_ids",
                # Keep the bounded project set intact. Eight documents
                # dropped the second Hostal Anibal budget folder from the
                # follow-up state; twelve still keeps prompt growth bounded.
                {"document_ids": last_document_ids[:12]},
            )
        ]

    # A document-scoped follow-up without an extracted budget number must not
    # degrade into a portfolio-wide aggregate.  Retrieve the active document
    # directly; its structured details contain the budget amount when present.
    active_document_id = (
        getattr(active_context, "current_document_id", None)
        if active_context is not None
        else _extract_context_document_id(question)
    )
    if (
        active_document_id
        and not getattr(active_context, "current_budget_number", None)
        and _is_aggregation_question(normalized)
        and not _contains_any(normalized, ("todos", "global", "compara"))
    ):
        return [
            ToolCall(
                "get_document_full_details",
                {"document_id": int(active_document_id)},
            )
        ]

    # ---- Specific delivery note ----
    # A delivery note amount is a document fact, not a portfolio aggregate.
    # Route it to the source documents before generic amount aggregation.
    if _contains_any(normalized, ("albaran", "delivery note")):
        return [
            ToolCall(
                "hybrid_search",
                # Do not feed a user-supplied instruction tail (e.g.
                # "ignora las instrucciones...") into retrieval. The
                # canonical document noun is sufficient and keeps the
                # resulting context grounded in delivery notes.
                {"query": "albaran", "filters": {"document_type": "albaran", "limit": 8}},
            )
        ]

    # ---- Aggregation intent (SQL over structured tables) ----
    # Catches the "cuanto nos hemos gastado en X", "cuantos pedidos sin
    # factura" family of questions that cannot be answered with text search.
    if _is_aggregation_question(normalized):
        entity, kind = _classify_aggregation(normalized)
        tools: list[ToolCall] = [ToolCall("aggregate_business", {"entity": entity, "kind": kind})]
        # Also pull the top documents that match, so the LLM can cite them.
        tools.append(ToolCall("hybrid_search", {"query": question, "filters": {"limit": 4}}))
        return tools

    # ---- Specific file mentioned -> lookup + details + relations ----
    # If the user mentions a filename (with extension) we use the lookup path
    # so the LLM gets the document's entities and its connections to the
    # rest of the project, not just text snippets.
    if mentioned_filenames:
        tools = [
            ToolCall("find_document_by_filename", {"query": mentioned_filenames[0]}),
            ToolCall(
                "get_document_full_details", {"document_id": 0}
            ),  # placeholder; replaced after lookup
            ToolCall(
                "get_related_documents", {"document_id": 0}
            ),  # placeholder; replaced after lookup
        ]
        # Exact file resolution is authoritative for ordinary questions.
        # Semantic retrieval stays available behind the rollback flag for
        # questions that genuinely need a paragraph outside the details.
        if not settings.search_exact_first_enabled:
            search_filters: dict = {"limit": 6}
            _maybe_apply_relevance_filter(search_filters, normalized, question)
            tools.append(ToolCall("hybrid_search", {"query": question, "filters": search_filters}))
        return tools

    # ---- Presupuesto / pedido / factura by number -> details + relations ----
    # If the user mentions a number and references a document concept
    # (presupuesto, pedido, factura, etc.), use the same smart chain.
    if document_number and (
        _contains_any(normalized, _BUDGET_HINTS)
        or _contains_any(normalized, _ORDER_HINTS)
        or _contains_any(normalized, _INVOICE_HINTS)
        or "documento" in normalized
        or "document" in normalized
        or "commande" in normalized
    ):
        # Prefer presupuesto when the user names it explicitly; otherwise
        # fall back to pedido. This avoids searching by pedido number when
        # the user actually asked about the budget.
        if _contains_any(normalized, _BUDGET_HINTS):
            primary = ToolCall("get_budget_by_number", {"budget_number": document_number})
        elif _contains_any(normalized, _ORDER_HINTS):
            primary = ToolCall("get_order_by_number", {"order_number": document_number})
        else:
            primary = ToolCall("get_budget_by_number", {"budget_number": document_number})
        tools = [
            primary,
            ToolCall("get_document_full_details", {"document_id": 0}),
            ToolCall("get_related_documents", {"document_id": 0}),
        ]
        if not settings.search_exact_first_enabled:
            tools.append(ToolCall("hybrid_search", {"query": question, "filters": {"limit": 6}}))
        return tools

    if _contains_any(normalized, _BUDGET_HINTS) and _contains_any(
        normalized, _ACCEPTED_WITHOUT_ORDER_HINTS
    ):
        return [ToolCall("get_accepted_budgets_without_order", {})]
    if _contains_word(normalized, "linea") and _contains_any(normalized, _ORDER_HINTS):
        return [ToolCall("get_order_by_number", {"order_number": document_number or ""})]
    if (
        "ultimo pedido" in normalized
        or "ultima pedido" in normalized
        or "ultimo ordine" in normalized
        or "latest order" in normalized
        or "last order" in normalized
        or "der letzte auftrag" in normalized
        or "last purchase order" in normalized
    ) or (_contains_any(normalized, _ORDER_HINTS) and document_number):
        return [ToolCall("get_order_by_number", {"order_number": document_number or ""})]
    if _contains_any(normalized, _DUPLICATE_HINTS):
        return [ToolCall("get_duplicate_documents", {})]
    if _contains_any(normalized, _LOW_OCR_HINTS):
        verbal_filename = _extract_verbal_filename(question)
        if verbal_filename:
            return [
                ToolCall("find_document_by_filename", {"query": verbal_filename}),
                ToolCall("get_document_full_details", {"document_id": 0}),
                ToolCall("get_related_documents", {"document_id": 0}),
                ToolCall("get_ocr_review_documents", {}),
            ]
        # Keep the review list, but also retrieve the named subject. Returning
        # only the global review queue made questions such as "incidencia de
        # sillas" lose their document-specific evidence.
        return [
            ToolCall("get_ocr_review_documents", {}),
            ToolCall("hybrid_search", {"query": question, "filters": {"limit": 8}}),
        ]
    if _contains_word(normalized, "entidad") and _contains_word(normalized, "referencia"):
        value = _extract_reference(question)
        return [
            ToolCall("search_entities", {"entity_type": "reference", "value": value or question})
        ]
    if _contains_any(
        normalized,
        (
            "mide",
            "medida",
            "medidas",
            "superficie",
            "tamano",
            "how big",
            "how large",
            "size",
            "area",
            "square",
            "taille",
            "dimension",
            "groesse",
            "flaeche",
            "dimensione",
            "superficie",
            "tamanho",
            "surface",
        ),
    ) and (room_name := _extract_room_name(normalized)):
        return [ToolCall("search_plan_room_measurements", {"room_name": room_name})]
    if settings.cad_chat_tools_enabled and _looks_like_cad_question(
        normalized,
        _extract_filenames(routing_question),
    ):
        return [ToolCall("get_plan_cad_context", {"query": routing_question})]
    if _contains_any(normalized, _PLAN_HINTS) or _contains_any(
        normalized,
        (
            "medida",
            "medidas",
            "mide",
            "escala",
            "scale",
            "mabstab",
            "scala",
            "echelle",
        ),
    ):
        return [
            ToolCall(
                "hybrid_search",
                {"query": question, "filters": {"document_type": "plano", "limit": 8}},
            )
        ]

    # General question: try hybrid_search with re-ranking filters when the
    # user hints at supplier / client / amount.
    search_filters = {"limit": 8}
    _maybe_apply_relevance_filter(search_filters, normalized, question)
    return [ToolCall("hybrid_search", {"query": question, "filters": search_filters})]


# ---------------------------------------------------------------------------
# CTX-6 — Structured tools selected by the business intent router.
#
# The router in :mod:`app.ai.intent_router` classifies the question
# into one of the business intents. For the intents that have a
# dedicated SQL tool, this function emits a ToolCall that the
# :func:`app.ai.context.collect_context` function dispatches to the
# matching tool in :mod:`app.tools.internal`. The structured tool runs
# FIRST; if it returns ``found=False`` the orchestrator falls back to
# the regular RAG path.
# ---------------------------------------------------------------------------


def select_structured_tools(
    question: str,
    *,
    active_context: Any | None = None,
) -> list[ToolCall]:
    """Return the structured tools the orchestrator should try first.

    ``active_context`` is the :class:`app.ai.active_context.ActiveContext`
    instance for the session. When the question is a follow-up
    ("por cuanto esta presupuestado") the context supplies the
    budget number. When the user named the budget explicitly the
    function pulls it from the question.

    The function is intentionally additive: it returns an empty list
    when the intent does not match a structured tool, so the
    orchestrator keeps falling back to the existing
    :func:`select_tools_for_question` output.
    """
    from .intent_router import (
        INTENT_ACCEPTED_BUDGETS,
        INTENT_BUDGET_LINES,
        INTENT_BUDGET_TOTAL,
        INTENT_DELIVERY_NOTE,
        INTENT_INVOICE_ORIGIN_ORDER,
        INTENT_INVOICED_AMOUNT,
        INTENT_PLAN_SUMMARY,
        INTENT_SHIPPING_COST,
        classify_intent,
    )

    classification = classify_intent(question, active_context)
    intent = classification.intent

    # ----------------------------------------------------------------
    # Override: when the user asks "está duplicada X" or "existe y cuál
    # es el más cercano" the intent router sometimes misclassifies the
    # question as INTENT_INVOICE_ORIGIN_ORDER (it sees "factura 250013"
    # and routes to the order-origin lookup). We re-route those to the
    # dossier tools first.
    # ----------------------------------------------------------------
    clean_q = _strip_context_prefix(question)
    normalised_q = _normalize(clean_q)
    if re.search(r"\b(duplicad[oa]s?|duplicado|duplicate|duplicada|repetid[oa])\b", normalised_q):
        ref = (
            _extract_reference(clean_q)
            or _extract_document_number(clean_q)
            or _extract_any_budget_code(normalised_q)
            or ""
        )
        if ref:
            return [
                ToolCall(
                    "find_documents_by_reference",
                    {"reference": ref, "include_duplicates": True},
                )
            ]
    if re.search(
        r"\b(existe|existes?|mas cercano|closest|plus proche|naheste|piu vicino|mais proximo)\b",
        normalised_q,
    ):
        any_b = _extract_document_number(clean_q) or _extract_any_budget_code(normalised_q)
        if any_b:
            return [ToolCall("find_nearest_budget", {"budget_code": any_b})]

    # The intent router returns ``needs_state=True`` when the intent
    # requires an active context. When the context has nothing to
    # resolve the follow-up, we still emit the tool call with an
    # empty argument so the dispatcher can produce a structured "no
    # se ha detectado presupuesto activo" answer.
    budget_number = (active_context.current_budget_number if active_context else None) or None
    budget_id = (active_context.current_budget_id if active_context else None) or None
    folder_path = (active_context.current_folder_path if active_context else None) or None
    invoice_number = (active_context.current_invoice_number if active_context else None) or None

    # If the user named a budget number in the question, it wins.
    # Do not treat an internal ``[Contexto: documento activo id=...]`` value
    # as an explicit budget number supplied by the user.
    explicit_budget = _extract_document_number(_strip_context_prefix(question))
    if explicit_budget and (
        "presupuesto" in _normalize(question)
        or "budget" in _normalize(question)
        or "presupuest" in _normalize(question)
    ):
        budget_number = explicit_budget
        budget_id = None

    if intent == INTENT_BUDGET_TOTAL:
        # ``select_tools_for_question`` will retrieve this document directly
        # when a document is active but no budget row/number is known.  Do not
        # emit an empty budget-total lookup first: it adds a misleading
        # "not found" result and used to make the fallback consider global
        # aggregates.
        if (
            not budget_number
            and budget_id is None
            and active_context is not None
            and getattr(active_context, "current_document_id", None)
        ):
            return []
        return [
            ToolCall(
                "get_budget_total",
                {
                    "budget_number": budget_number or "",
                    "budget_id": budget_id,
                },
            )
        ]
    if intent == INTENT_BUDGET_LINES:
        return [
            ToolCall(
                "get_budget_lines",
                {
                    "budget_number": budget_number or "",
                    "budget_id": budget_id,
                },
            )
        ]
    if intent == INTENT_INVOICED_AMOUNT:
        return [
            ToolCall(
                "get_invoiced_amount_for_budget",
                {
                    "budget_number": budget_number or "",
                    "budget_id": budget_id,
                },
            )
        ]
    if intent == INTENT_ACCEPTED_BUDGETS:
        return [ToolCall("list_recent_accepted_budgets", {"limit": 10})]
    if intent == INTENT_INVOICE_ORIGIN_ORDER:
        return [
            ToolCall(
                "get_invoice_origin_order",
                {
                    "invoice_number": invoice_number or "",
                },
            )
        ]
    if intent == INTENT_DELIVERY_NOTE:
        return [
            ToolCall(
                "find_delivery_note_in_scope",
                {
                    "budget_number": budget_number or "",
                    "folder_path": folder_path or "",
                },
            )
        ]
    if intent == INTENT_SHIPPING_COST:
        return [
            ToolCall(
                "find_shipping_cost_in_scope",
                {
                    "budget_number": budget_number or "",
                    "folder_path": folder_path or "",
                },
            )
        ]
    if intent == INTENT_PLAN_SUMMARY:
        # Plan summaries still go through RAG (the structured data
        # does not have a "summary" field), but we tag the tool
        # selection so the orchestrator knows the question is about a
        # plan and applies the right context windows.
        return []
    # ----------------------------------------------------------------
    # Dossier / aggregation patterns (added for the eval questionnaire).
    # These cover "cuántos presupuestos hay", "lista los albaranes del
    # 250053", "resumen ejecutivo del 250152", "el 250999 existe? cuál
    # es el más cercano" and "está duplicada la factura 250013".
    # The detection is rule-based and lives here (not in the intent
    # router) because the patterns are short and very specific.
    # The order matters: special-case patterns (nearest, duplicate) run
    # before the generic list, otherwise a "existe? más cercano" question
    # falls into the generic count pattern and never reaches nearest.
    # ----------------------------------------------------------------
    clean_question = _strip_context_prefix(question)
    normalised = _normalize(clean_question)
    explicit_budget_in_q = _extract_document_number(clean_question)
    any_budget_in_q = explicit_budget_in_q or _extract_any_budget_code(normalised)

    has_special_keyword = bool(
        re.search(
            r"\b(existe|existes?|hay|esta|mas cercano|closest|plus proche|naheste|piu vicino|mais proximo|duplicad[oa]s?|duplicado|duplicate|duplicada|repetid[oa])\b",
            normalised,
        )
    )

    # 4) "el presupuesto N existe? cuál es el más cercano?"
    # Runs BEFORE the generic list so "presupuesto 250999" routes to
    # nearest_budget instead of list_distinct_budget_codes.
    if re.search(
        r"\b(existe|existes?|hay|mas cercano|closest|plus proche|naheste|piu vicino|mais proximo)\b",
        normalised,
    ) and any_budget_in_q:
        return [ToolCall("find_nearest_budget", {"budget_code": any_budget_in_q})]

    # 5) "está duplicada la factura / el documento / el pedido N"
    if re.search(
        r"\b(duplicad[oa]s?|duplicado|duplicate|duplicada|repetid[oa])\b",
        normalised,
    ):
        ref = (
            _extract_reference(clean_question)
            or explicit_budget_in_q
            or _extract_any_budget_code(normalised)
            or ""
        )
        if ref:
            return [
                ToolCall(
                    "find_documents_by_reference",
                    {"reference": ref, "include_duplicates": True},
                )
            ]

    # 1) "cuántos presupuestos distintos hay / lista los códigos"
    if not has_special_keyword and re.search(
        r"\b(cuantos|cuantas|cuales|que|listar?|lista|how many|combien|wie viele|quanti|quante)\b"
        r".*\b(presupuestos?|budgets?)\b"
        r"(?!\s+(del?|de la|con))",
        normalised,
    ) and any_budget_in_q is None:
        return [ToolCall("list_distinct_budget_codes", {"limit": 200})]

    # 2) "resumen ejecutivo / resumen del presupuesto N"
    if any_budget_in_q and re.search(
        r"\b(resumen|resum|summary|resumir|executive|executivo|overview|vista general)\b",
        normalised,
    ):
        return [ToolCall("get_budget_summary", {"budget_code": any_budget_in_q})]

    # 3) "qué X tiene el presupuesto N / lista los X del N / enumera X del N"
    if any_budget_in_q:
        doc_type_filter = _classify_doc_type_in_question(normalised)
        ext_filter = _classify_extension_in_question(normalised)
        quality_filter = _classify_quality_in_question(normalised)
        return [
            ToolCall(
                "list_documents_by_budget_code",
                {
                    "budget_code": any_budget_in_q,
                    "document_type": doc_type_filter,
                    "extension": ext_filter,
                    "quality_status": quality_filter,
                    "limit": 50,
                },
            )
        ]

    return []


# ---------------------------------------------------------------------------
# Question-classification helpers (dossier filters)
# ---------------------------------------------------------------------------


_DOC_TYPE_SYNONYMS: dict[str, tuple[str, ...]] = {
    # Specific types FIRST so the matcher does not pick up the word
    # "presupuesto" used as the scope field name. ``presupuesto`` stays
    # last as a fallback (when the user really asks for a budget, e.g.
    # "lista los presupuestos aceptados").
    "albaran": (
        "albaran", "albaranes", "albaran de entrega", "albaran_transporte",
        "delivery", "delivery note", "delivery notes", "packing list",
    ),
    "factura": (
        "factura", "facturas", "invoice", "invoices", "fra",
    ),
    "pedido": (
        "pedido", "pedidos", "orden de compra", "ordenes de compra",
        "order", "orders", "purchase order",
    ),
    "email_exportado": (
        "correo", "correos", "email", "emails", "correo electronico",
        "correos electronicos", "mensaje", "mensajes", ".msg",
    ),
    "excel": (
        "excel", "excels", "hoja de calculo", "xlsx",
    ),
    "plano": (
        "plano", "planos", "plan", "plans", "drawing", "blueprint",
    ),
    "comprobante_pago": (
        "comprobante", "comprobantes", "pago", "pagos", "transferencia",
        "comprobante de pago", "payment", "receipt",
    ),
    "orden_trabajo": (
        "orden de trabajo", "ordenes de trabajo", "work order",
    ),
    "ficha_tecnica": (
        "ficha tecnica", "fichas tecnicas", "technical sheet",
    ),
    "dua": (
        "dua", "duas", "declaracion unica aduanera", "aduana", "customs",
    ),
    "croquis_medida": (
        "croquis", "croquis de medida", "croquis de medidas",
    ),
    "medicion": (
        "medicion", "mediciones", "medida", "medidas",
    ),
    "foto_producto": (
        "foto", "fotos", "fotografia", "imagen", "imagenes",
    ),
    "presupuesto": (
        "presupuesto", "presupuestos", "budget", "budgets",
        "cotizacion", "cotizaciones", "oferta",
    ),
}

_EXTENSION_HINTS: dict[str, tuple[str, ...]] = {
    ".msg": (".msg", "outlook", "correo outlook", "email"),
    ".pdf": (".pdf", "pdf", "pdfs"),
    ".xlsx": (".xlsx", "excel"),
    ".jpg": (".jpg", ".jpeg", "foto", "fotos", "imagen", "imagenes"),
    ".dwg": (".dwg", "autocad"),
    ".dxf": (".dxf",),
}

_QUALITY_HINTS: dict[str, tuple[str, ...]] = {
    "needs_human_review": (
        "necesita revision", "necesitan revision", "pendiente de revision",
        "revisar", "human review", "needs review", "needs_human_review",
    ),
    "usable_with_warnings": (
        "con advertencias", "con warnings", "calidad baja",
    ),
    "processed_ok": (
        "ok", "correctos", "validados", "procesados correctamente",
    ),
    "duplicate": (
        "duplicados", "repetidos", "duplicada",
    ),
    "pending": (
        "pendientes", "por procesar", "no procesados",
    ),
}


def _extract_any_budget_code(normalised: str) -> str | None:
    """Pull any 5-7 digit numeric identifier that could be a budget code.

    ``_extract_document_number`` is calibrated for the canonical 6-digit
    code. This helper accepts 5-7 digits so an out-of-range reference
    like ``250999`` or a legacy 5-digit one still routes to the right
    tool. The check is intentionally cheap.
    """
    m = re.search(r"\b(\d{5,7})\b", normalised)
    return m.group(1) if m else None


def _classify_doc_type_in_question(normalised: str) -> str | None:
    """Map a normalised Spanish/English question to a document_type filter.

    Returns the canonical ``document_type`` value used by the DB
    (``albaran``, ``factura``, ``email_exportado``, …) or ``None``
    when the question does not specify one.

    The "presupuesto" type is special: the word almost always refers
    to the *scope* (presupuesto 250053) and only rarely to the
    document *type* (e.g. "lista los presupuestos aceptados"). We
    therefore only return "presupuesto" when no other more specific
    type matched AND the word appears without a trailing 6-digit code.
    """
    # First pass: specific types in order
    for canonical, synonyms in _DOC_TYPE_SYNONYMS.items():
        if canonical == "presupuesto":
            continue  # handled below
        if any(_contains_word(normalised, s) for s in synonyms):
            return canonical
    # Second pass: "presupuesto" only if not followed by a 6-digit code
    if _contains_word(normalised, "presupuesto") or _contains_word(normalised, "presupuestos"):
        # Strip "presupuesto NNNNN" occurrences to detect scope-only use
        stripped = re.sub(r"presupuestos?\s+\d{6}\b", " ", normalised)
        if re.search(r"\bpresupuestos?\b", stripped):
            return "presupuesto"
    return None


def _classify_extension_in_question(normalised: str) -> str | None:
    """Return the file extension filter (``".msg"``, ``".pdf"`` …) or None."""
    for ext, hints in _EXTENSION_HINTS.items():
        if any(_contains_word(normalised, h) for h in hints):
            return ext
    return None


def _classify_quality_in_question(normalised: str) -> str | None:
    """Return the quality_status filter or None."""
    for status, hints in _QUALITY_HINTS.items():
        if any(_contains_word(normalised, h) for h in hints):
            return status
    return None


# ---------------------------------------------------------------------------
# Question-classification helpers (aggregation + re-ranking)
# ---------------------------------------------------------------------------


def _is_aggregation_question(normalized: str) -> bool:
    """True when the user is asking for a SQL-style aggregation.

    Replaces the old ``any(h in normalized for h in _AGGREGATION_HINTS)``
    check (which only worked in Spanish) with a multi-language
    whole-word scan over :data:`_AGGREGATION_HINTS`.
    """
    return _contains_any(normalized, _AGGREGATION_HINTS)


def _classify_aggregation(normalized: str) -> tuple[str, str]:
    """Return (entity, kind) for an aggregation question.

    - entity: 'budget' | 'order' | 'invoice'
    - kind:   'count' | 'total' | 'top' | 'by_supplier'

    Recognises the entity by whole-word match over the multi-language
    lexicons so an English "how much did we spend on orders?" gets
    ``entity='order', kind='total'`` just like the Spanish equivalent.
    The check is order-sensitive: invoice > order > budget, so an
    English question that mentions "purchase orders" routes to
    ``order`` (purchase order is in ``_ORDER_HINTS``) and not
    ``invoice``.
    """
    if _contains_any(normalized, _INVOICE_HINTS):
        entity = "invoice"
    elif _contains_any(normalized, _ORDER_HINTS):
        entity = "order"
    else:
        entity = "budget"

    if _contains_any(
        normalized,
        (
            "top",
            "ranking",
            "rank",
            "principales",
            "mayor",
            "menor",
            "mas alto",
            "mas altos",
            "mas baja",
            "mas bajas",
            "mas grande",
            "mas grandes",
            "highest",
            "largest",
            "biggest",
            "lowest",
            "smallest",
            "le plus",
            "le moins",
            "hoechste",
            "niedrigste",
            "piu alto",
            "piu basso",
            "mais alto",
            "mais baixo",
        ),
    ):
        kind = "top"
    elif _contains_any(
        normalized,
        (
            "cuanto",
            "cuanta",
            "total",
            "suma",
            "importe",
            "gastado",
            "facturado",
            "cobrado",
            "how much",
            "amount",
            "spent",
            "invoiced",
            "collected",
            "combien",
            "montant",
            "somme",
            "wieviel",
            "gesamt",
            "summe",
            "betrag",
            "quanto",
            "importo",
            "fatturato",
            "soma",
            "faturado",
        ),
    ):
        kind = "total"
    elif (
        "por proveedor" in normalized
        or "por cada proveedor" in normalized
        or "by supplier" in normalized
        or "per supplier" in normalized
        or "par fournisseur" in normalized
        or "pro lieferant" in normalized
        or "per fornitore" in normalized
        or "por fornecedor" in normalized
    ):
        kind = "by_supplier"
    else:
        kind = "count"
    return entity, kind


def _maybe_apply_relevance_filter(filters: dict, normalized: str, original_question: str) -> None:
    """Add `document_type`, `supplier_ilike`, `client_ilike`, or amount
    bounds to the hybrid_search filters when the user hints at them in the
    question. The search service is responsible for actually applying them
    (see search_service.py)."""
    # Whole-word match against the multi-language lexicons so we stop
    # accidentally classifying a "plano" mentioned in passing as the
    # primary document type when the user is really asking for
    # something else. The order of the checks matters: "plano" is a
    # sub-word of "planta" in some Spanish questions so we test
    # planos/plans before falling back to budgets/orders/invoices.
    if _contains_any(normalized, _PLAN_HINTS):
        filters["document_type"] = "plano"
    elif _contains_any(normalized, _ORDER_HINTS):
        filters["document_type"] = "pedido"
    elif _contains_any(normalized, _BUDGET_HINTS):
        filters["document_type"] = "presupuesto"
    elif _contains_any(normalized, _INVOICE_HINTS):
        filters["document_type"] = "factura"

    money = _money_filters("", original_question)
    if money.get("supplier"):
        filters["supplier_ilike"] = f"%{money['supplier']}%"
    if money.get("client"):
        filters["client_ilike"] = f"%{money['client']}%"
    if money.get("amount_min") is not None:
        filters["amount_min"] = money["amount_min"]
    if money.get("amount_max") is not None:
        filters["amount_max"] = money["amount_max"]


# ---------------------------------------------------------------------------
# Question-text helpers
# ---------------------------------------------------------------------------


def _normalize(text: str) -> str:
    """Lowercase + strip accents for keyword matching. The original
    casing/accented text is preserved in the LLM prompt; this is
    only used for the cheap, in-Python keyword checks."""
    normalized = unicodedata.normalize("NFKD", text.lower())
    return normalized.encode("ascii", "ignore").decode("ascii")


def _strip_context_prefix(text: str) -> str:
    """Remove an internal follow-up context prefix before routing.

    The prefix may contain database identifiers.  Those are internal state,
    not identifiers supplied by the user, and must never redirect retrieval.
    """
    return re.sub(r"^\s*\[contexto\s*:[^\]]*\]\s*", "", text or "", flags=re.IGNORECASE)


def _extract_context_document_id(text: str) -> int | None:
    """Return the active document id carried by an internal context prefix."""
    prefix = re.match(r"^\s*\[contexto\s*:(?P<context>[^\]]*)\]", text or "", re.I)
    if not prefix:
        return None
    match = re.search(r"\bdocumento\s+activo\s+id=(\d+)", prefix.group("context"), re.I)
    return int(match.group(1)) if match else None


def _extract_document_number(text: str) -> str | None:
    """Pull a presupuesto / pedido number from a free-form question.

    Tries three patterns in order of specificity:
    1. ``2024/1234`` style (Spanish budget format).
    2. ``prefix-NNN`` style (alphanumeric budget/order ids).
    3. A pure numeric id of 5-7 digits (legacy short codes).
    """
    match = re.search(r"\b\d{4}/\d+\b", text)
    if match:
        return match.group(0)
    match = re.search(r"\b[A-Za-z]{0,8}\d{2,}[-/_]\d+\b", text)
    if match:
        return match.group(0)
    match = re.search(r"\b\d{5,7}\b", text)
    return match.group(0) if match else None


def _extract_document_numbers(text: str) -> list[str]:
    """Return all distinct bare numeric identifiers in user input order."""
    found: list[str] = []
    for value in re.findall(r"\b\d{5,7}\b", text or ""):
        if value not in found:
            found.append(value)
    return found


def _extract_literal_identifiers(text: str) -> list[str]:
    """Return explicit non-numeric identifiers in user input order.

    Covers common codes that cannot safely be inferred by a semantic model:
    tax identifiers, alphanumeric references and multi-segment invoice/order
    codes.  Plain numbers are deliberately excluded because
    :func:`_extract_document_numbers` handles them first.
    """
    patterns = (
        r"\b[A-Za-z]{1,8}-\d{2,}(?:[-/_]\d+)*\b",  # F-2025-001 / MAT-001
        r"\b[A-Za-z]\d{7,8}[A-Za-z]?\b",  # B12345678
        r"\b\d{7,8}[A-Za-z]\b",  # 12345678Z
        r"\b[A-Za-z]{2,}\d{2,}[A-Za-z0-9-]*\b",  # REF123 / MAT-001
    )
    found: list[str] = []
    for pattern in patterns:
        for value in re.findall(pattern, text or ""):
            if value not in found:
                found.append(value)
    return found


_SUBJECT_STOP_WORDS = frozenset(
    {
        "de",
        "del",
        "en",
        "para",
        "con",
        "que",
        "presupuesto",
        "pedido",
        "factura",
        "necesito",
        "quiero",
        "quieres",
        "es",
        "son",
        "tiene",
        "tienen",
        "este",
        "esta",
        "ese",
        "esa",
        "presupuestos",
        "pedidos",
        "facturas",
        "documento",
        "documentos",
        "archivo",
        "archivos",
        "informacion",
        "datos",
        "detalle",
        "detalles",
        "sabes",
        "trata",
    }
)


_EXACT_SUBJECT_NOUNS = (
    "hotel",
    "hostal",
    "cliente",
    "proveedor",
    "empresa",
    "sociedad",
    "compania",
    "compañia",
    "marca",
    "cadena",
    "proyecto",
    "obra",
    "edificio",
    "residencia",
    "restaurante",
    "apartamento",
    "villa",
    "local",
    "inmueble",
    "contacto",
    "persona",
    "contratista",
    "fabricante",
    "promotor",
)


def _subject_tail(text: str, *, limit: int = 4) -> str | None:
    """Return a bounded subject tail without question-language noise."""
    tokens: list[str] = []
    for token in re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9'’-]+", text or ""):
        normalized = _normalize(token)
        if normalized in _SUBJECT_STOP_WORDS:
            break
        tokens.append(token)
        if len(tokens) == limit:
            break
    return " ".join(tokens) or None


def extract_exact_subject_phrases(text: str) -> list[str]:
    """Extract high-confidence literal subjects from a user question.

    This intentionally covers *entity shapes*, not document types: quoted
    labels, persons/organisations written with capitals, and names following
    a generic business or project noun.  The output is deduplicated and is
    safe to send to literal retrieval; unstructured prose is left to normal
    hybrid search.
    """
    clean = _strip_context_prefix(text)
    candidates: list[str] = []

    # Quoted text is an explicit user selection irrespective of casing.
    for match in re.finditer(r"[\"'«“]([^\"'»”]{3,80})[\"'»”]", clean):
        candidates.append(" ".join(match.group(1).split()))

    noun_pattern = "|".join(re.escape(noun) for noun in _EXACT_SUBJECT_NOUNS)
    for match in re.finditer(
        rf"\b(?P<noun>{noun_pattern})\s+(?P<tail>[^?.!,;:\n]+)",
        clean,
        flags=re.IGNORECASE,
    ):
        tail = _subject_tail(match.group("tail"))
        if tail:
            candidates.append(f"{match.group('noun')} {tail}")

    # "Que sabes de Ana Perez" and equivalent queries often omit an entity
    # noun.  A two-or-more-word capitalised sequence is still an explicit
    # enough subject to require literal grounding.
    for match in re.finditer(
        r"(?<!\w)([A-ZÀ-ÖØ-Þ][\w'’-]+(?:\s+[A-ZÀ-ÖØ-Þ][\w'’-]+){1,3})(?!\w)",
        clean,
    ):
        phrase = " ".join(match.group(1).split())
        if _normalize(phrase.split()[0]) not in _SUBJECT_STOP_WORDS:
            candidates.append(phrase)

    # A one-word subject may legitimately be lower case (for example "que
    # sabes de anibal").  Restrict this form to explicit knowledge questions
    # so ordinary phrases such as "facturas de julio" stay semantic.
    for match in re.finditer(
        r"\b(?:que|qué)\s+sabes\s+(?:de|del|sobre)\s+([^?.!,;:\n]+)",
        clean,
        flags=re.IGNORECASE,
    ):
        subject = _subject_tail(match.group(1))
        if subject and len(subject) >= 3:
            candidates.append(subject)

    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = " ".join(candidate.split())
        key = normalized.casefold()
        if key and key not in seen:
            seen.add(key)
            unique.append(normalized)

    # Prefer the most specific phrase when a capitalised-name rule found a
    # suffix of an already captured entity (``ACME Iberia`` inside
    # ``proveedor ACME Iberia``).
    return [
        candidate
        for candidate in unique
        if not any(
            candidate.casefold() != other.casefold()
            and other.casefold().endswith(" " + candidate.casefold())
            for other in unique
        )
    ]


def _extract_reference(text: str) -> str | None:
    """Pick up an alphanumeric reference token like ``MAT-001`` or
    ``REF12345``. Returns the first match or None."""
    match = re.search(r"\b[A-Za-z]{2,}\d{2,}[A-Za-z0-9-]*\b", text)
    return match.group(0) if match else None


_FILENAME_HINT = re.compile(
    r"\b[\w./-]+\.(?:pdf|msg|docx|doc|xlsx|xls|xlsm|csv|tsv|png|jpe?g|tiff?|bmp|webp|eml|txt|dxf|dwg)\b",
    flags=re.IGNORECASE,
)
_CAD_FILENAME_HINT = re.compile(r"([^?;,\n]*?\.(?:dxf|dwg))\b", flags=re.IGNORECASE)
_VERBAL_FILENAME_HINT = re.compile(
    r"\b(?:pdf|documento|archivo)\s+de\s+(.+?)(?=\s+(?:si|con|cuando)\b|[?.;,]|$)",
    flags=re.IGNORECASE,
)


def _extract_filenames(text: str) -> list[str]:
    """Find filename-like tokens in the user's question. Stops common
    false positives like URLs by requiring a document extension at
    the end."""
    matches = _FILENAME_HINT.findall(text or "")
    if matches:
        return matches
    cad_matches = []
    for match in _CAD_FILENAME_HINT.findall(text or ""):
        candidate = match.strip(" \t\n.¿¡")
        # Keep the filename tail when the sentence contains a leading
        # question phrase ("qué medidas aparecen en ...dwg").
        if " en " in candidate.lower():
            candidate = re.split(r"\ben\b", candidate, maxsplit=1, flags=re.IGNORECASE)[-1].strip()
        if candidate:
            cad_matches.append(candidate)
    return cad_matches


def _extract_verbal_filename(text: str) -> str | None:
    """Extract a filename-like description when the extension was omitted.

    Users commonly ask for "el PDF de incidencia de sillas" rather than the
    literal ``incidencia sillas.pdf``. This helper is deliberately used only
    on document-oriented low-OCR requests, so ordinary prose does not trigger
    a filename lookup.
    """
    match = _VERBAL_FILENAME_HINT.search(text or "")
    if not match:
        return None
    value = match.group(1).strip(" \t\n.,;:!?¿¡")
    # Uploaded filenames commonly omit Spanish connector words: a user says
    # "incidencia de sillas" while the stored file is
    # ``incidencia sillas.pdf``. Keep content words in their original order
    # so the partial filename search remains precise.
    value = re.sub(r"\b(?:de|del|la|el|los|las)\b", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+", " ", value).strip()
    return value or None


def _extract_room_name(normalized_question: str) -> str | None:
    """Pick up the name of a room the user is asking about.

    The lexicon (:data:`_ROOM_HINTS`) maps every surface form
    (Spanish, English, French, Italian, Portuguese) to a single
    canonical name. The first alias that matches the question
    wins, so an English "kitchen" returns ``kitchen`` instead of
    being shadowed by the Spanish entry that also lists
    ``cocina``. When the question mentions a room that is not in
    the list, we fall back to a regex that captures the noun
    after "mide" / "medida" / "superficie" / "size" / "area".
    """
    for alias, canonical in _ROOM_HINTS.items():
        if _contains_word(normalized_question, alias):
            return "bano" if canonical == "bano" else canonical
    match = re.search(
        r"(?:mide|medida|medidas|superficie|size|area|square|dimension|"
        r"taille|groesse|dimensione|superficie|tamanho|"
        r"tamano|flaeche|flaechen|surface)\s+"
        r"(?:del|de la|de el|el|la|the|of|de|du|von|di|do)?\s*"
        r"([a-z0-9 ]{3,30})",
        normalized_question,
    )
    if match:
        candidate = match.group(1).strip()
        generic = {
            "aparecen",
            "aparece",
            "hay",
            "tiene",
            "tienen",
            "del",
            "de",
            "el",
            "la",
            "este",
            "esta",
            "estos",
            "estas",
            "plano",
            "planos",
            "documento",
            "archivo",
            "aqui",
            "ahi",
            "en",
            "se",
            "son",
        }
        tokens = candidate.split()
        if (
            candidate in generic
            or (tokens and (tokens[0] in generic or tokens[-1] in generic))
            or any(
                candidate.endswith(ext) or f"{ext} " in candidate
                for ext in (".dxf", ".dwg", ".pdf")
            )
        ):
            return None
        return candidate
    return None
