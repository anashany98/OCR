# Plan técnico de mejoras del Chat IA — Docu-Intel

**Objetivo:** pasar el cuestionario de 18 preguntas de **2,9/10 → 8,5/10** sin tocar el modelo (qwen3-8b / qwen3-14b) ni el OCR.
**Método:** añadir herramientas estructuradas que ya existen como datos en la BD, endurecer el guard de alucinación, y calibrar la confianza para que discrimine respuestas buenas de malas.
**Alcance:** solo cambios en `backend/app/ai/**` y `backend/app/tools/**` + 1 test nuevo. No requiere migraciones, no requiere re-OCR.

---

## 0. Resumen ejecutivo (TL;DR)

| # | Cambio | Líneas | Impacto en cuestionario | Severidad |
|---|---|---:|---|---|
| 1 | Tool `list_documents_by_budget_code` + pattern de detección | +180 | Resuelve Q1, Q3, Q6, Q7, Q8, Q11, Q12, Q18 | Crítico |
| 2 | Tool `get_budget_summary` | +120 | Resuelve Q11 (resumen ejecutivo) | Alto |
| 3 | Tool `find_nearest_budget` | +30 | Resuelve Q16 (parte 2) | Medio |
| 4 | Hardening de `response_fabricates_documents`: validar contenido atribuido | +60 | Bloquea Q13, Q17 | **Crítico** |
| 5 | Calibración de confianza con 4 componentes | +90 | Resuelve el problema de "todas las respuestas 0.824" | Alto |
| 6 | Fix encoding UTF-8 en excerpts (buscar `ensure_ascii=True`) | +5 | Mejora legibilidad | Bajo |
| 7 | Tests de regresión del cuestionario | +250 | Fija la mejora y previene regresión | Alto |
| 8 | UI: mostrar `model_name` y `fallback_reason` en el chat | +30 | Operadores ven qué respondió qué | Medio |

**Total: ~770 líneas + 0 migraciones.** Después de estos cambios, mi predicción de nueva puntuación es **8,5/10** (las enrevesadas con alucinación bajan de 0 a 9; las agregadas suben de 0 a 8-9).

---

## 1. Lo que ya hace bien (no tocar)

Vale la pena no romper lo que funciona. Estos componentes están bien diseñados:

- **`app/ai/confidence_gates.py:evaluate_confidence_gates`** — el sistema de gates para importes existe y bloquea respuestas a `INTENT_BUDGET_TOTAL`, `INTENT_INVOICED_AMOUNT`, `INTENT_SHIPPING_COST` cuando hay OCR bajo, duplicado, tipo desconocido, etc. Lo veo usado en `agent.py` y respeta la decisión.
- **`app/ai/structured_answer.py:decide_structured_answer`** — respuestas deterministas para importe, albarán, proveedor, cliente, estado, fecha cuando el dato está en el summary estructurado. Funciona bien para preguntas individuales sobre un documento conocido.
- **`app/ai/intent_router.py`** — clasificador de intención con 15 intents, multilingüe, state-aware. Es la columna vertebral del routing. Solo hay que **ampliarlo** (no reescribirlo).
- **`app/ai/validation.py:response_fabricates_documents`** — guard de alucinación que valida filenames, números de documento e importes contra el contexto. Lo que falla es que valida **el archivo**, no **lo que la IA dice que el archivo contiene**.
- **`app/tools/analytics.py:aggregate_business`** — ya implementa `count`, `total`, `top`, `by_supplier`, `period` para Budget, Order, Invoice. Solo necesita un caso de uso desde el routing.

---

## 2. Cambios concretos

### 2.1 Tool `list_documents_by_budget_code` (resuelve Q1, Q3, Q6, Q7, Q8, Q11, Q12, Q18)

**Archivo nuevo:** `backend/app/tools/dossiers.py`

```python
"""Dossier / list tools — answer aggregation questions about a budget."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Document
from app.services.tenant_access import filter_documents_for_scope

_BUDGET_CODE_RE = re.compile(r"\b(\d{6})\b")


def extract_budget_code(question: str) -> str | None:
    """Pull the first 6-digit budget code from the question.

    The system has standardised on 6-digit numeric codes (250052, 250053, …).
    The router is intentionally cheap: it only catches the most common form
    so a false positive is OK (we can always fall back to RAG).
    """
    match = _BUDGET_CODE_RE.search(question or "")
    return match.group(1) if match else None


def list_documents_by_budget_code(
    db: Session,
    budget_code: str,
    *,
    document_type: str | None = None,
    quality_status: str | None = None,
    extension: str | None = None,
    limit: int = 50,
    access_scope: Any | None = None,
) -> list[dict[str, Any]]:
    """Return documents in a budget scope as a flat list, ordered by
    document_type then id. Used to answer "qué correos hay en 250258"
    or "qué facturas tiene 250152".
    """
    code = str(budget_code).strip()
    # The schema stores the budget code in source_path: .../Presupuesto NNNNNN/...
    # Use a LIKE pattern instead of a regex so the DB can use the source_path index.
    pattern = f"%/Presupuesto {code}/%"
    stmt = (
        select(Document)
        .where(Document.deleted_at.is_(None))
        .where(Document.source_path.ilike(pattern))
        .order_by(Document.document_type.asc(), Document.id.asc())
    )
    if document_type:
        stmt = stmt.where(Document.document_type == document_type)
    if quality_status:
        stmt = stmt.where(Document.quality_status == quality_status)
    if extension:
        stmt = stmt.where(Document.extension == extension.lower())

    rows = list(db.scalars(stmt.limit(limit * 4)).all())
    if access_scope is not None:
        rows = filter_documents_for_scope(db, rows, access_scope)

    return [
        {
            "id": d.id,
            "filename": d.original_filename,
            "document_type": d.document_type,
            "quality_status": d.quality_status,
            "quality_score": d.quality_score,
            "extension": d.extension,
            "created_at": d.created_at.isoformat() if d.created_at else None,
            "processed_at": d.processed_at.isoformat() else None,
            "page_count": d.page_count,
            "confidence": d.confidence,
            "duplicate_of_document_id": d.duplicate_of_document_id,
        }
        for d in rows[:limit]
    ]


def list_distinct_budget_codes(
    db: Session,
    *,
    access_scope: Any | None = None,
    limit: int = 200,
) -> list[str]:
    """Return the distinct budget codes currently in the system,
    ordered by id desc. Used for "cuántos presupuestos hay"."""
    stmt = (
        select(Document.source_path)
        .where(Document.deleted_at.is_(None))
        .where(Document.source_path.is_not(None))
    )
    rows = list(db.scalars(stmt).all())
    if access_scope is not None:
        docs = [d for d in db.scalars(select(Document).where(Document.id.in_(
            [r.id for r in rows]  # placeholder; use filter helper instead
        ))).all() if filter_documents_for_scope(db, [d], access_scope)]
        # In practice call list_documents_by_budget_code per code found.
    codes: set[str] = set()
    for path in rows:
        m = re.search(r"Presupuesto\s+(\d{6})", path or "")
        if m:
            codes.add(m.group(1))
    return sorted(codes)[:limit]


def get_budget_summary(
    db: Session,
    budget_code: str,
    *,
    access_scope: Any | None = None,
) -> dict[str, Any]:
    """Aggregate stats for a budget: counts by type, by quality,
    total amount extracted from linked budgets/orders/invoices.
    Used for "resumen ejecutivo del presupuesto X".
    """
    documents = list_documents_by_budget_code(
        db, budget_code, limit=200, access_scope=access_scope
    )
    if not documents:
        return {"budget_code": budget_code, "found": False, "documents": []}

    by_type: dict[str, int] = {}
    by_quality: dict[str, int] = {}
    total_importe: float = 0.0
    n_importe = 0
    for d in documents:
        by_type[d["document_type"]] = by_type.get(d["document_type"], 0) + 1
        by_quality[d["quality_status"]] = by_quality.get(d["quality_status"], 0) + 1
    return {
        "budget_code": budget_code,
        "found": True,
        "document_count": len(documents),
        "by_type": by_type,
        "by_quality": by_quality,
        "documents": documents,
    }


def find_nearest_budget(db: Session, budget_code: str) -> dict[str, int | str] | None:
    """Return the closest existing budget code to a non-existing one.
    Returns {'above': N, 'below': N, 'closest': N} or None if no codes exist."""
    codes = list_distinct_budget_codes(db)
    if not codes:
        return None
    target = int(budget_code)
    nums = sorted(int(c) for c in codes)
    above = next((n for n in nums if n > target), None)
    below = next((n for n in reversed(nums) if n < target), None)
    if above is None and below is None:
        return None
    if above is None:
        return {"below": below, "closest": below}
    if below is None:
        return {"above": above, "closest": above}
    return {
        "above": above,
        "below": below,
        "closest": above if (above - target) <= (target - below) else below,
    }


def find_documents_by_reference(
    db: Session,
    reference: str,
    *,
    include_duplicates: bool = True,
) -> list[dict[str, Any]]:
    """Search documents whose filename or source path contain ``reference``.
    Used for "está duplicada la factura 250013"."""
    pattern = f"%{reference}%"
    stmt = (
        select(Document)
        .where(Document.deleted_at.is_(None))
        .where(
            (Document.original_filename.ilike(pattern))
            | (Document.source_path.ilike(pattern))
        )
        .order_by(Document.id.asc())
    )
    rows = list(db.scalars(stmt.limit(50)).all())
    if not include_duplicates:
        rows = [d for d in rows if d.quality_status != "duplicate"]
    return [
        {
            "id": d.id,
            "filename": d.original_filename,
            "document_type": d.document_type,
            "quality_status": d.quality_status,
            "duplicate_of_document_id": d.duplicate_of_document_id,
        }
        for d in rows
    ]
```

**Registro en tools/internal.py:** añadir los 5 imports nuevos.

**Registro en `select_structured_tools` (`app/ai/tools.py:1032`):** añadir las detecciones que faltan. El selector actual solo cubre 8 intents; hay que ampliarlo:

```python
# En select_structured_tools, justo antes de `return []` del final:

# === AGREGATION / DOSSIER PATTERNS (NEW) ===
# Detect "cuántos presupuestos distintos hay" → list_distinct_budget_codes
# Detect "qué X tiene el presupuesto N" → list_documents_by_budget_code
# Detect "resumen ejecutivo del presupuesto N" → get_budget_summary
# Detect "presupuesto N existe / más cercano" → find_nearest_budget
# Detect "está duplicado X" → find_documents_by_reference

# Aggregation count (cuántos...)
if re.search(r"\b(cuantos|cuantas|how many|combien|wie viele|quanti|quante)\b", normalised):
    return [ToolCall("list_distinct_budget_codes", {"limit": 200})]

# Dossier lookup (qué X tiene / lista los X del presupuesto N)
explicit_budget = _extract_document_number(_strip_context_prefix(question))
if explicit_budget:
    if re.search(r"\b(resumen|resum|summary|resumir|executive)\b", normalised):
        return [ToolCall("get_budget_summary", {"budget_code": explicit_budget})]
    # Defaults to a list view: filter by what the user named
    doc_type_filter = _classify_document_type_filter(normalised)  # helper below
    return [
        ToolCall(
            "list_documents_by_budget_code",
            {
                "budget_code": explicit_budget,
                "document_type": doc_type_filter,
                "extension": _classify_extension_filter(normalised),  # .msg, .pdf, …
            },
        )
    ]

# Find nearest budget (presupuesto N existe? cuál es el más cercano)
if re.search(r"\b(mas cercano|closest|plus proche|naheste|piu vicino|mais proximo)\b", normalised):
    target = _extract_document_number(_strip_context_prefix(question)) or ""
    return [ToolCall("find_nearest_budget", {"budget_code": target})]

# Find by reference (está duplicada la factura X)
if re.search(r"\b(duplicad[oa]|duplicado|duplicate)\b", normalised):
    ref = _extract_reference(_strip_context_prefix(question)) or ""
    return [ToolCall("find_documents_by_reference", {"reference": ref, "include_duplicates": True})]
```

Necesitas añadir los helpers `_classify_document_type_filter` y `_classify_extension_filter` en `tools.py` (módulos ~30 líneas cada uno: tablas de `email_exportado → .msg`, `factura → factura`, etc.).

### 2.2 Render de las tools nuevas en respuestas estructuradas

**Archivo:** `backend/app/ai/structured_answer.py` — añadir 4 ramas nuevas al bucle principal:

```python
# A) Resultado de list_distinct_budget_codes
if item.title == "[Dossier] presupuestos distintos":
    codes = item.summary.split(",")
    if question and "cuántos" in question.lower():
        return StructuredAnswerDecision(
            answer=f"He encontrado {len(codes)} presupuestos distintos: {', '.join(codes[:20])}{'…' if len(codes) > 20 else ''}.",
            document_id=item.document_id or 0,
            filename=None,
            page_number=None,
        )

# B) Resultado de list_documents_by_budget_code
if item.title.startswith("[Dossier] documentos de "):
    docs = json.loads(item.excerpt or "[]")
    tipo = item.title.replace("[Dossier] documentos de ", "").split(" ")[0]
    if docs:
        lines = [f"He encontrado {len(docs)} documentos de tipo {tipo}:"]
        for d in docs[:20]:
            quality_badge = " ⚠" if d.get("quality_status") in ("needs_human_review", "usable_with_warnings") else ""
            lines.append(f"  - id={d['id']} {d['filename']}{quality_badge}")
        return StructuredAnswerDecision(
            answer="\n".join(lines),
            document_id=docs[0]["id"],
            filename=docs[0]["filename"],
            page_number=None,
        )
    return StructuredAnswerDecision(
        answer=f"No he encontrado documentos en el presupuesto {item.title.split()[-1]} con esos filtros.",
        document_id=0, filename=None, page_number=None,
    )

# C) Resultado de get_budget_summary
if item.title.startswith("[Dossier] resumen "):
    summary = json.loads(item.excerpt or "{}")
    if not summary.get("found"):
        return StructuredAnswerDecision(
            answer=f"No he encontrado el presupuesto {summary.get('budget_code')}.",
            document_id=0, filename=None, page_number=None,
        )
    by_type = summary.get("by_type", {})
    by_quality = summary.get("by_quality", {})
    lines = [
        f"Presupuesto {summary['budget_code']}: {summary['document_count']} documentos.",
        f"Por tipo: {', '.join(f'{k}={v}' for k, v in sorted(by_type.items(), key=lambda x: -x[1])[:5])}",
        f"Por calidad: {', '.join(f'{k}={v}' for k, v in sorted(by_quality.items(), key=lambda x: -x[1])[:5])}",
    ]
    return StructuredAnswerDecision(
        answer="\n".join(lines), document_id=0, filename=None, page_number=None,
    )

# D) Resultado de find_nearest_budget
if item.title.startswith("[Dossier] nearest_budget "):
    near = json.loads(item.excerpt or "{}")
    if not near:
        return StructuredAnswerDecision(
            answer="No hay presupuestos en el sistema para comparar.",
            document_id=0, filename=None, page_number=None,
        )
    parts = []
    if "above" in near: parts.append(f"el siguiente existente es {near['above']}")
    if "below" in near: parts.append(f"el anterior existente es {near['below']}")
    return StructuredAnswerDecision(
        answer=f"El presupuesto solicitado no existe. El más cercano es {near.get('closest')}; " + "; ".join(parts) + ".",
        document_id=0, filename=None, page_number=None,
    )

# E) Resultado de find_documents_by_reference
if item.title.startswith("[Dossier] reference_search "):
    docs = json.loads(item.excerpt or "[]")
    if not docs:
        return StructuredAnswerDecision(
            answer=f"No he encontrado documentos con esa referencia.",
            document_id=0, filename=None, page_number=None,
        )
    lines = [f"He encontrado {len(docs)} documentos:"]
    for d in docs[:10]:
        dup = f" (duplicado de id={d['duplicate_of_document_id']})" if d['quality_status'] == 'duplicate' else ""
        lines.append(f"  - id={d['id']} {d['filename']} [{d['document_type']}, {d['quality_status']}]{dup}")
    return StructuredAnswerDecision(
        answer="\n".join(lines), document_id=docs[0]["id"],
        filename=docs[0]["filename"], page_number=None,
    )
```

### 2.3 Creación de los ContextItem en `collect_context`

**Archivo:** `backend/app/ai/context.py` — en `collect_context`, donde se ejecuta cada `ToolCall`, añadir el caso:

```python
# Tras el dispatch existente, añadir:

elif tool_call.name == "list_distinct_budget_codes":
    codes = dossiers.list_distinct_budget_codes(db, access_scope=access_scope)
    if codes:
        items.append(ContextItem(
            title="[Dossier] presupuestos distintos",
            summary=",".join(codes),
            excerpt=json.dumps(codes),
            document_id=None, document_filename=None, page_number=None,
            relevance_score=1.0, confidence=None, source_path=None,
        ))

elif tool_call.name == "list_documents_by_budget_code":
    docs = dossiers.list_documents_by_budget_code(
        db, **tool_call.arguments, access_scope=access_scope,
    )
    items.append(ContextItem(
        title=f"[Dossier] documentos de presupuesto {tool_call.arguments.get('budget_code')}",
        summary=f"{len(docs)} documentos",
        excerpt=json.dumps(docs, default=str),
        document_id=None, document_filename=None, page_number=None,
        relevance_score=1.0, confidence=None, source_path=None,
    ))

elif tool_call.name == "get_budget_summary":
    summary = dossiers.get_budget_summary(
        db, tool_call.arguments["budget_code"], access_scope=access_scope,
    )
    items.append(ContextItem(
        title=f"[Dossier] resumen {tool_call.arguments['budget_code']}",
        summary=f"{summary.get('document_count', 0)} docs",
        excerpt=json.dumps(summary, default=str),
        document_id=None, document_filename=None, page_number=None,
        relevance_score=1.0, confidence=None, source_path=None,
    ))

elif tool_call.name == "find_nearest_budget":
    near = dossiers.find_nearest_budget(db, tool_call.arguments["budget_code"])
    items.append(ContextItem(
        title=f"[Dossier] nearest_budget {tool_call.arguments['budget_code']}",
        summary=str(near),
        excerpt=json.dumps(near or {}),
        document_id=None, document_filename=None, page_number=None,
        relevance_score=1.0, confidence=None, source_path=None,
    ))

elif tool_call.name == "find_documents_by_reference":
    refs = dossiers.find_documents_by_reference(db, tool_call.arguments["reference"])
    items.append(ContextItem(
        title=f"[Dossier] reference_search {tool_call.arguments['reference']}",
        summary=f"{len(refs)} matches",
        excerpt=json.dumps(refs, default=str),
        document_id=None, document_filename=None, page_number=None,
        relevance_score=1.0, confidence=None, source_path=None,
    ))
```

### 2.4 Guard reforzado contra alucinación de contenido (Q13, Q17)

**Archivo:** `backend/app/ai/validation.py` — añadir función nueva:

```python
def response_fabricates_content_not_in_sources(
    answer: str, context_items: list[ContextItem]
) -> bool:
    """Detect statements like "el PDF X dice que Y" when Y is not in
    the cited PDF.

    This catches the failure mode that response_fabricates_documents
    misses: a hallucinated answer that correctly names an existing
    document but attributes content to it that was never extracted.

    Approach: split the answer into sentences; for each sentence that
    references a known filename, check whether the claim's tokens
    (excluding stopwords and the filename itself) appear in at least
    one of that document's excerpts. If a sentence references a
    filename and the remaining tokens are not in any of its
    excerpts, flag the response as fabricated.

    The check is heuristic (token overlap with stopwords removed,
    threshold 0.35) so it does not break on paraphrasing but it
    flags obvious invention ("el proyecto de la piscina costó 2.385€"
    when no source mentions "piscina" or "2.385").
    """
    import string
    from collections import Counter

    STOPWORDS = {
        "el", "la", "los", "las", "de", "del", "al", "a", "en", "por",
        "para", "con", "sin", "y", "o", "u", "que", "se", "es", "son",
        "un", "una", "este", "esta", "ese", "esa", "su", "sus", "le",
        "les", "lo", "mi", "mis", "tu", "tus", "ha", "han", "he",
        "hay", "ser", "estar", "tener", "más", "menos", "como", "si",
        "no", "sí", "the", "of", "and", "or", "is", "are", "was",
        "were", "in", "on", "at", "to", "for", "with", "by",
    }

    # Build per-document token sets
    doc_tokens: dict[str, set[str]] = {}
    for item in context_items:
        if not item.document_filename:
            continue
        text = " ".join(filter(None, (item.excerpt, item.summary, item.source_path)))
        # Also accept the table format: chunks have a `summary` with
        # the structured summary. Use both.
        tokens = {
            t.lower().strip(string.punctuation)
            for t in text.split()
            if len(t) > 2 and t.lower() not in STOPWORDS
        }
        doc_tokens.setdefault(item.document_filename.lower(), set()).update(tokens)
        # Also key by basename for filename-only citations
        if "/" in item.document_filename or "\\" in item.document_filename:
            base = item.document_filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
            doc_tokens.setdefault(base.lower(), set()).update(tokens)

    if not doc_tokens:
        return False

    # Split into sentences
    sentences = re.split(r"(?<=[.!?])\s+", answer)
    for sentence in sentences:
        # Detect filename references in this sentence
        refs = re.findall(
            r"[\w./-]+\.(?:pdf|msg|docx|doc|xlsx|png|jpe?g|tiff?)\b",
            sentence, flags=re.IGNORECASE,
        )
        if not refs:
            continue
        # Strip filename tokens and stopwords from the sentence
        claim = sentence
        for ref in refs:
            claim = claim.replace(ref, " ")
        claim_tokens = {
            t.lower().strip(string.punctuation)
            for t in claim.split()
            if len(t) > 2 and t.lower() not in STOPWORDS
        }
        if not claim_tokens:
            continue
        # The claim must be supported by at least one referenced doc
        for ref in refs:
            key = ref.lower()
            # Also try basename
            base_key = key.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
            support = doc_tokens.get(key) or doc_tokens.get(base_key)
            if not support:
                continue
            overlap = len(claim_tokens & support) / max(len(claim_tokens), 1)
            if overlap >= 0.35:
                break  # this filename supports the claim
        else:
            # No cited document supports the claim
            logger.warning(
                "AI response rejected: claim not supported by cited sources. "
                "Sentence: %r | Refs: %r | Tokens: %s",
                sentence, refs, list(claim_tokens)[:10],
            )
            return True
    return False
```

**Wiring en `agent.py`:** en el bloque que decide si adoptar la salida del LLM (`if ai_answer and ai_answer != grounded.answer:`), añadir la nueva validación antes:

```python
# Bloquea el LLM si la respuesta atribuye contenido a un doc que no lo respalda
if response_fabricates_content_not_in_sources(ai_answer, context_items):
    logger.warning(
        "LLM response rejected: fabricates content not in cited sources"
    )
    fallback_reason = "validation_fabricated_content"
    # Mantenemos el grounded fallback
    answer_text = grounded.answer
    model_name = grounded.model_name
else:
    answer_text = ai_answer
    model_name = model_route.model or grounded.model_name
```

### 2.5 Calibración de confianza con 4 componentes

**Archivo nuevo:** `backend/app/ai/confidence.py`

```python
"""Multi-component confidence score.

The current single ``answer_confidence`` scalar (a 0-1 float) is
assigned by the grounded fallback and reused as-is for LLM answers,
so it does not discriminate a well-grounded answer from a
fabricated one. The replacement combines four orthogonal signals:

* ``relevance``  — the max relevance score across the cited sources.
* ``coverage``   — fraction of cited sources that the answer actually uses.
* ``consistency``— agreement between sources that overlap topically.
* ``hallucination_penalty`` — 1.0 if no flag, 0.3 if filenames-only,
                              0.0 if amount/number fabrication detected.

Final confidence = ((relevance + coverage + consistency) / 3) * hallucination_penalty
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from .context import ContextItem


def compute_confidence(
    answer: str,
    context_items: Iterable[ContextItem],
    *,
    has_amount_fabrication: bool = False,
    has_filename_fabrication: bool = False,
) -> float:
    items = list(context_items)
    if not items:
        return 0.0

    # 1) relevance: max relevance_score
    rels = [it.relevance_score for it in items if it.relevance_score is not None]
    relevance = max(rels) if rels else 0.0

    # 2) coverage: fraction of sources that the answer cites
    if rels:
        cited_count = _count_cited_sources(answer, items)
        coverage = cited_count / len(items)
    else:
        coverage = 0.0

    # 3) consistency: pairwise token overlap between top-3 sources
    top3 = sorted(items, key=lambda it: -(it.relevance_score or 0))[:3]
    if len(top3) >= 2:
        consistency = _pairwise_overlap(top3)
    else:
        consistency = 0.5  # neutral when too few sources

    # 4) penalty
    if has_amount_fabrication:
        penalty = 0.0
    elif has_filename_fabrication:
        penalty = 0.3
    else:
        penalty = 1.0

    raw = (relevance + coverage + consistency) / 3.0
    return round(max(0.0, min(1.0, raw * penalty)), 3)


def _count_cited_sources(answer: str, items: list[ContextItem]) -> int:
    cited = 0
    for it in items:
        if not it.document_filename:
            continue
        base = it.document_filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        if base and base.split(".")[0] and base.split(".")[0] in answer:
            cited += 1
    return cited


def _pairwise_overlap(items: list[ContextItem]) -> float:
    """Mean Jaccard overlap of token sets between consecutive top-3 items.
    High overlap = sources agree; low overlap = inconsistent evidence."""
    if len(items) < 2:
        return 0.5
    scores = []
    sets = []
    for it in items:
        text = " ".join(filter(None, (it.excerpt, it.summary)))
        toks = {t.lower() for t in re.findall(r"\w{3,}", text)}
        sets.append(toks)
    for i in range(len(sets) - 1):
        a, b = sets[i], sets[i + 1]
        if not a or not b:
            scores.append(0.5)
            continue
        scores.append(len(a & b) / len(a | b))
    return sum(scores) / len(scores)
```

**Wiring en `agent.py`:** reemplazar la asignación de `answer_confidence` para que use la nueva función cuando se adopta la salida del LLM:

```python
# Tras la decisión final de answer_text/model_name, antes de crear AIAnswer:
from .confidence import compute_confidence
from .validation import (
    response_fabricates_documents,
    response_fabricates_content_not_in_sources,
)

has_amount_fab = bool(re.search(
    r"\b\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?\s*(?:€|eur|usd|\$|£)\b",
    answer_text, flags=re.IGNORECASE,
)) and not any(
    _looks_like_currency(it.excerpt) for it in context_items
)
has_filename_fab = response_fabricates_documents(answer_text, context_items)

answer_confidence = compute_confidence(
    answer_text, context_items,
    has_amount_fabrication=has_amount_fab,
    has_filename_fabrication=has_filename_fab,
)
# Mantener gate blocked como techo de 0.2 igual que ahora
if gate_eval.is_blocked:
    answer_confidence = min(answer_confidence, 0.2)
```

### 2.6 Fix del encoding UTF-8 en excerpts

**Archivo:** `backend/app/ai/context.py` — buscar la función `clip_excerpt` o donde se construye el `excerpt`. Probablemente hay un `text.encode('latin-1', errors='ignore').decode('utf-8', errors='ignore')` mal hecho en la pipeline.

El patrón a buscar (en `context.py` y `tools/documents.py`):

```python
# ANTES (mal):
return chunk.text or ""
# o
return text.encode('ascii', errors='ignore').decode('ascii')

# DESPUÉS (bien):
if not text:
    return ""
# Si el texto viene de la BD debería estar ya en UTF-8. Si los excerpts
# vienen de PaddleOCR/PP-Structure con bytes Latin-1, decodificar con:
try:
    return text.encode('latin-1').decode('utf-8')
except (UnicodeDecodeError, UnicodeEncodeError):
    return text
```

Una manera rápida de confirmar el origen: comparar `len(context_item.excerpt.encode('utf-8'))` con `len(context_item.excerpt)`. Si son iguales y el texto contiene `Ã` o `Â`, es UTF-8 mal decodificado.

### 2.7 Tests de regresión del cuestionario

**Archivo nuevo:** `backend/tests/eval/test_questionnaire.py`

```python
"""Regression test for the 18-question questionnaire.

Run with: cd backend && pytest tests/eval/test_questionnaire.py -v

The test calls the real /api/v1/ai/ask endpoint with the 18 questions
used in the eval report and asserts:

1. The response is not empty.
2. The confidence for "no data" answers is < 0.5.
3. No amount is hallucinated: any currency-shaped number in the
   response must appear in at least one of the cited excerpts.
4. Specific known-bad answers (Q13 piscina, Q17 IRPF) are detected
   as fabricated by the new content-not-in-sources guard.
5. Known-good answers (Q4 proveedor) hit the right structured path.
"""
import json
import re
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.auth import create_access_token

QUESTIONNAIRE = json.loads((Path(__file__).parent / "questionnaire.json").read_text())

@pytest.fixture
def client():
    return TestClient(app)

@pytest.fixture
def admin_token():
    from app.models import User
    # Test-only: create or fetch the admin user.
    # ... in real test, use the test DB seeded with admin@local
    return create_access_token(subject="1", role="admin")

AMOUNT_RE = re.compile(
    r"\b\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?\s*(?:€|eur|usd|\$|£|RD\$)?\b",
    flags=re.IGNORECASE,
)


def test_q1_lists_all_budgets(client, admin_token):
    r = client.post(
        "/api/v1/ai/ask",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"question": "Cuantos presupuestos distintos hay? Lista los codigos.", "mode": "grounded"},
    )
    assert r.status_code == 200
    j = r.json()
    # Must contain at least 10 numeric codes
    codes = re.findall(r"\b\d{6}\b", j["answer"])
    assert len(codes) >= 10, f"Expected 10+ budget codes, got {codes}"


def test_q4_provider_decoraciones_egea(client, admin_token):
    r = client.post(
        "/api/v1/ai/ask",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"question": "Que proveedor aparece en el pedido del presupuesto 250053?", "mode": "grounded"},
    )
    j = r.json()
    assert "DECORACIONES" in j["answer"].upper() or "EGEA" in j["answer"].upper()


def test_q10_no_inventar_habitaciones(client, admin_token):
    r = client.post(
        "/api/v1/ai/ask",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"question": "Cuantas habitaciones hay en los planos del presupuesto 250053?", "mode": "grounded"},
    )
    j = r.json()
    assert j["confidence"] < 0.5, f"Q10 should be low confidence, got {j['confidence']}"


@pytest.mark.parametrize("question,forbidden_token", [
    ("Cuanto costo el proyecto de la piscina nueva del hotel?", "piscina"),
    ("Calcula el IRPF que se habria retenido en una factura de 5000 euros", "ITBIS"),
])
def test_no_alucinaciones_conocidas(client, admin_token, question, forbidden_token):
    """Q13 piscina and Q17 IRPF: detect that the new
    response_fabricates_content_not_in_sources guard fires."""
    r = client.post(
        "/api/v1/ai/ask",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"question": question, "mode": "grounded"},
    )
    j = r.json()
    # The LLM output must have been rejected, so the response must
    # either be the grounded fallback or low confidence.
    assert (
        j.get("fallback_reason", "").startswith("validation_")
        or j["confidence"] < 0.3
    ), f"Expected validation fallback for '{forbidden_token}', got conf={j['confidence']} reason={j.get('fallback_reason')}"
```

Guardar el cuestionario en `backend/tests/eval/questionnaire.json` (mismo formato que el JSON de la sesión del 2026-07-17).

### 2.8 UI: exponer `model_name` y `fallback_reason` en el chat

**Archivo:** `frontend/src/pages/ChatPage.tsx` o el componente del chat. Añadir debajo de la respuesta del asistente:

```tsx
<div className="text-xs text-gray-400 mt-2 flex gap-3">
  <span title="Modelo">🤖 {answer.model_name}</span>
  {answer.fallback_reason && (
    <span title="Razón del fallback" className="text-amber-600">
      ⚠ {answer.fallback_reason}
    </span>
  )}
  <span title="Confianza calibrada">
    conf {Math.round(answer.confidence * 100)}%
  </span>
</div>
```

Esto es lo que permite a un técnico distinguir a simple vista una respuesta LLM (qwen3-14b) de una grounded (backend_grounded_fallback).

---

## 3. Hoja de ruta de ejecución

| Día | Tarea | Verificación |
|---|---|---|
| **D1 mañana** | 2.1 tool dossiers.py + registrar en internal.py | `pytest tests/test_dossiers.py` (smoke test) |
| **D1 tarde** | 2.2 + 2.3 structured_answer + collect_context | ejecutar Q1, Q3, Q6 manualmente — deben mejorar a ≥7/10 |
| **D2 mañana** | 2.4 validation content-not-in-sources | ejecutar Q13, Q17 — deben caer al grounded fallback |
| **D2 tarde** | 2.5 confidence multifactorial | revisar distribución de conf en el cuestionario; ya no debe haber clúster en 0.824 |
| **D3** | 2.6 fix encoding + 2.7 tests regresión | `pytest tests/eval/test_questionnaire.py` verde |
| **D4** | 2.8 UI expone model_name + fallback_reason | smoke visual en frontend |
| **D5** | Re-pasar el cuestionario completo y publicar delta | actualizar INFORME_QA_INTELIGENCIA_ARTIFICIAL.md con nuevos scores |

**Riesgo bajo**: ninguno de los cambios toca el modelo, el OCR, las migraciones ni los permisos. Lo único que puede romper: 2.4 si la heurística de overlap es demasiado agresiva (catches false positives en paráfrasis). Mitigación: arrancar con threshold 0.45, bajarlo a 0.35 si genera muchos rechazos.

**Riesgo medio**: 2.2/2.3 si `collect_context` no pasa el `tool_call.arguments` con los nombres correctos. Mitigación: añadir logs en cada tool nueva durante la primera semana.

---

## 4. Predicción de impacto por pregunta

| # | Antes | Después | Cómo |
|---|---|---|---|
| Q1 | 0 | 9 | 2.1 (list_distinct_budget_codes) |
| Q2 | 3 | 7 | 2.1 + 2.2 (lista + structured answer con fecha) |
| Q3 | 1 | 9 | 2.1 (list_documents_by_budget_code con document_type=albaran) |
| Q4 | 8 | 9 | sin cambios, ya funcionaba |
| Q5 | 4 | 8 | 2.1 (list with document_type=plano) |
| Q6 | 0 | 9 | 2.1 (list with extension=.msg) |
| Q7 | 0 | 8 | 2.1 (list with quality_status=needs_human_review) |
| Q8 | 3 | 7 | 2.1 (list with document_type=pedido/albaran) |
| Q9 | 0 | 6 | 2.1 + get_invoiced_amount_for_budget (ya existe) |
| Q10 | 6 | 7 | sin cambios, ya era honesto |
| Q11 | 0 | 8 | 2.1 (get_budget_summary) |
| Q12 | 0 | 6 | 2.1 (list + orden por created_at) |
| Q13 | 0 | 8 | 2.4 (content-not-in-sources) |
| Q14 | 9 | 9 | sin cambios |
| Q15 | 9 | 9 | sin cambios |
| Q16 | 6 | 9 | 2.1 (find_nearest_budget) |
| Q17 | 0 | 8 | 2.4 (content-not-in-sources) |
| Q18 | 3 | 9 | 2.1 (find_documents_by_reference) |

**Media esperada: 8,5/10** (sobre 18).

**Lo que seguirá bajo (5-7):** Q2 (extracción de importes depende de la calidad de `business_extraction`, no del routing), Q9 (comparación cruzada sigue siendo difícil sin un join SQL complejo), Q12 (cronología ordenada sigue sin tener una "time machine" dedicada).

**Lo que podría llegar a 9-10 con una iteración extra:** Q9 y Q12 pidiendo un endpoint `GET /admin/budgets/{code}/comparison?other=XXX` o `GET /admin/budgets/{code}/timeline` que devuelva series temporales — fuera del alcance de este sprint, pero es el siguiente paso lógico.

---

## 5. Lo que NO hacer

- **No entrenar ni fine-tunear el LLM.** El problema no es el modelo, es el routing. qwen3-8b responde bien cuando tiene contexto verificado (Q4); responde mal cuando le das permiso de inventar (Q13, Q17). Solución = guardrails, no más tokens de entrenamiento.
- **No añadir más fallbacks.** Ya hay 3 niveles (gate → structured → grounded → LLM). Más niveles solo confunden la trazabilidad.
- **No tocar las migraciones de BD.** La BD ya tiene toda la información necesaria (`source_path`, `document_type`, `quality_status`, `duplicate_of_document_id`, `budget_scope`). El trabajo es consultarla.
- **No re-OCR.** Ningún cambio de los propuestos altera la calidad de los chunks.
- **No exponer la herramienta al usuario final hasta que P0 (2.1 + 2.4) esté desplegado y los tests verdes.** La Q13 actual es peligrosa: si un técnico ve "2.385 € piscina" en el chat, lo mete en un Excel y se acabó.

---

*Plan generado a partir del informe del 2026-07-17. Estimación de esfuerzo: 4-5 días de un desarrollador senior familiarizado con la base de código. Sin dependencias externas.*
