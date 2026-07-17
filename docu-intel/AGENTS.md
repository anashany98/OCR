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
- **FASE 8.2:** ~~DB indexes — `hnsw.ef_search` sigue en script SQL manual `optimize_vector_indexes.sql`~~ **Resuelto** en `codex/plan-pgvector-graph-rag`. El override se aplica ahora desde `app.services.vector_store._apply_hnsw_ef_search` (`SET LOCAL hnsw.ef_search`) con el valor configurable `search_hnsw_ef_search` (default 40, validado por Pydantic en `[20, 200]`). Ver `docs/PLAN_ARQUITECTURA_PGVECTOR_GRAPH_RAG.md` §2.3.

## Decisiones arquitectónicas vinculantes (no negociables)

- **Una sola plataforma vectorial: PostgreSQL + pgvector.** No se instala ni se referencia Milvus, Zilliz Cloud, Qdrant, Weaviate ni Pinecone en ninguna capa (Docker, `requirements*.txt`, `pyproject.toml`, código de aplicación). Cualquier PR que añada `pymilvus` o un servicio `milvus` en compose se rechaza en revisión. Auditoría: `grep -ril "milvus\|pymilvus\|zilliz" .` debe seguir devolviendo cero ocurrencias fuera del propio plan.
- **Graph RAG sobre tablas relacionales.** No se instala Neo4j ni Apache AGE; las relaciones se modelan con tablas SQL planas (`graph_entities`, `graph_relations`, `graph_relation_evidence`, etc., migración `0064_graph_rag_relational`).
- **Orden de escalado:** primero SQL/índices → HNSW `ef_search` → re-particionado. Nunca "migrar a otra base vectorial".

Plan completo y razonamiento: `docs/PLAN_ARQUITECTURA_PGVECTOR_GRAPH_RAG.md` (rama `codex/plan-pgvector-graph-rag`).

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

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

When the user types `/graphify`, use the installed graphify skill or instructions before doing anything else.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- Dirty graphify-out/ files are expected after hooks or incremental updates; dirty graph files are not a reason to skip graphify. Only skip graphify if the task is about stale or incorrect graph output, or the user explicitly says not to use it.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
