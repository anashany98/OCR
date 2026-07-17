# Informe de auditoría pgvector — 2026-07-16

> Documento vivo. La tabla de resultados se actualiza tras cada
> ejecución de `python -m scripts.benchmark_pgvector_configs`. Hasta
> entonces este archivo es el **placeholder** definido en el plan
> `PLAN_ARQUITECTURA_PGVECTOR_GRAPH_RAG.md` §2.2, listo para ser
> rellenado con datos reales.

## 1. Contexto

* **Rama:** `codex/plan-pgvector-graph-rag`
* **Migración base:** `0063_ai_answer_fallback_reason` (siguiente: `0064_graph_rag_relational`)
* **Decisión arquitectónica:** se mantiene PostgreSQL + pgvector como
  única plataforma vectorial. No se compara contra Milvus ni
  cualquier otra base externa (ver `PLAN_ARQUITECTURA_PGVECTOR_GRAPH_RAG.md` §0).

## 2. Dimensiones medidas (plan §2.2)

Estos campos se rellenan al ejecutar el benchmark contra el entorno
de desarrollo. La consulta exacta está en
`scripts/benchmark_pgvector_configs.py::_render_markdown`.

| Métrica | Valor actual | Notas |
| --- | --- | --- |
| Volumen de documentos (`SELECT count(*) FROM documents WHERE deleted_at IS NULL`) | _pendiente_ | medir en dev antes de tocar parámetros |
| Número de chunks (`SELECT count(*) FROM document_chunks`) | _pendiente_ | id. |
| Crecimiento mensual estimado | _pendiente_ | delta `created_at` últimos 3 meses × proyección |
| Tamaño embeddings (`pg_total_relation_size('document_chunks')`) | _pendiente_ | — |
| Tamaño del índice HNSW | _pendiente_ | `pg_size_pretty(pg_relation_size(c.oid))` joined con `pg_class` |
| Latencia p50/p95/p99 `/search/hybrid` | _pendiente_ | `EXPLAIN (ANALYZE, BUFFERS)` sobre la consulta vectorial |
| Recall@5 / Recall@10 (golden set RAG) | _pendiente_ | `backend/scripts/build_runtime_rag_golden.py` |
| Throughput con 7 concurrentes | _pendiente_ | `locust` o `asyncio.gather` contra `/search/hybrid` |
| Throughput con filtros de permisos activos | _pendiente_ | mismo, con `budget_scope_id` + `project_id` |
| Tiempo del reranker local BGE-v2-m3 | _pendiente_ | medir en `reranker.py` |
| Tiempo hasta el primer token SSE `/ai/ask/stream` | _pendiente_ | contrato `test_ai_stream_immediate.py` |

## 3. Resultados del benchmark (plan §2.6)

Esta tabla se regenera ejecutando:

```bash
cd docu-intel/backend
python -m scripts.benchmark_pgvector_configs \
    --golden ../artifacts/answer-quality/runtime-golden.jsonl \
    --output ../artifacts/pgvector-benchmark.json \
    --markdown ../docs/INFORME_AUDITORIA_PGVECTOR_<fecha>.md \
    --concurrency 1 7 \
    --ef-search 20 40 60 80 120
```

| Configuración | Recall@5 | Recall@10 | p50 (ms) | p95 (ms) | p99 (ms) | QPS@1 | QPS@7 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| _pendiente de primera ejecución_ | — | — | — | — | — | — | — |

## 4. Reglas de no regresión

Antes de promover cualquier optimización a producción, los nuevos
valores deben cumplir las dos reglas del plan §2.2:

* **Recall@10** no puede empeorar respecto al baseline.
* **p95** de `/search/hybrid` no puede subir más de un 10 %.

## 5. Decisiones derivadas

A rellenar tras la primera ejecución:

* **`hnsw.ef_search` definitivo:** _pendiente_
* **¿Activar reranker por defecto?** _pendiente_ (criterio: p95 ≤ 250 ms, plan §2.3 punto 6)
* **¿Activar IVFFlat?** _pendiente_ (criterio: índice HNSW > 50 % RAM, plan §2.5)
* **¿Particionar `document_chunks`?** _pendiente_ (umbral: > 10 M filas + p95 degrada, plan §2.3 punto 10)
