# AGENTS.md — Docu-Intel

## Contexto
- **Repo:** backend FastAPI + Celery. Python 3.11. OCR en `app/ocr/`, IA en `app/ai/`, recuperación en `app/services/`.
- **Stack OCR:** Tesseract 5 (CPU) → PaddleOCR 3.x (GPU) → PP-Structure (GPU, tablas/layout), orquestado por `CascadingOCREngine`.
- **Stack IA:** chunking → embeddings (OpenAI-compat) → pgvector + búsqueda híbrida + reranker cross-encoder → respuesta *grounded* con LLM local.
- **GPUs:** 2× RTX 4070, una por worker vía `CUDA_VISIBLE_DEVICES`.

## Reglas para el agente
1. **No rompas la interfaz `BaseOCREngine`** (`extract(image_path: Path) -> OCRResult`) ni la firma pública de `embed_many` / `search_*`.
2. **Añade tests** para cada cambio de comportamiento y mantén verdes los existentes.
3. Cada motor OCR sigue siendo **stateless por página**; no introduzcas estado global salvo singletons de modelo ya existentes.
4. Cambios **incrementales y revisables**: un commit por tarea.
5. No introduzcas dependencias nuevas sin añadirlas a `requirements.txt` y al `Dockerfile`.
6. Respeta la política existente "sin hash fallback silencioso" en embeddings.

## Estado de FASEs

### Completadas
- **FASE 1:** Aceleración OCR (FP16, paralelismo, DPI ladder, timeouts)
- **FASE 2:** Extracción estructurada (19/19 tests)
- **FASE 3:** Reactivar PaddleOCR + bugs A1/A2 + umbrales cascada
- **FASE 4:** VLM table extraction (22 tests nuevos)
- **FASE 5:** Pre-clasificación por content_route
- **FASE 6:** Did-you-mean + reranker fix + métricas
- **FASE 8.1:** Document-level embedding (alternativa a late chunking) — `Document.embedding` se puebla en ingesta (`document_embedding_pipeline.apply_document_embedding` dentro de `_replace_document_chunks`) y se fusiona con la búsqueda por chunk vía RRF en `search_service._search_semantic_pass`. Gated por `settings.search_use_document_embedding`.

### Pendientes
- **FASE 7:** CI (mypy strict, coverage 70%) — golden-ocr GPU queda como deuda: requiere runner GPU dedicado (hoy no valida PaddleOCR en GPU)
- **FASE 8.2:** DB indexes — `hnsw.ef_search` sigue en script SQL manual `optimize_vector_indexes.sql` (no en migración Alembic; activarlo requiere reinicio de Postgres)

## Estructura clave
```
app/
  ocr/
    cascading.py      — Cascade orchestrator (Tier 1-4)
    tesseract.py      — Tesseract 5 engine
    paddle.py         — PaddleOCR 3.x engine
    pp_structure.py   — PP-Structure engine
    preprocess.py     — Image preprocessing per engine
    dots_mocr.py      — VLM OCR (Tier 4)
  ai/
    agent.py          — Main orchestrator (<800 lines)
    context.py        — Context collection + grounded response
    local_answer.py   — One-shot LLM call
    did_you_mean.py   — Similar document suggestions
    prompts.py        — AI message building
  services/
    business_extraction.py — Budget/invoice line extraction
    vlm_table_extraction.py — VLM table→JSON (FASE 4)
    search_service.py  — Hybrid search + reranker
    embeddings.py      — Embedding providers
    vector_store.py    — pgvector store
  parsers/
    content_router.py  — Document type classification
    pdf.py             — PDF parser with per-page OCR
```
