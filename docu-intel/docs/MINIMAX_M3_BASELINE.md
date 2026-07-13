# MiniMax M3 — Baseline reproducible (FASE 0)

Fecha: 2026-07-13
Rama: `fix/remediacion-auditoria-2026-07`
Commit de partida: `a2399bd`

## 1. Inventario operativo

### 1.1 Hardware

| Recurso | Valor |
|---|---|
| CPU | AMD Ryzen 9 9950X (16 núcleos / 32 hilos) |
| RAM | 98 GB total, 36 GB libres |
| GPU 0 | NVIDIA GeForce RTX 4070 — 12 GB VRAM, driver 610.62 |
| GPU 1 | NVIDIA GeForce RTX 4070 — 12 GB VRAM, driver 610.62 |
| OS | Microsoft Windows 11 Pro |

### 1.2 Modelos y servicios

| Servicio | Valor |
|---|---|
| `AI_PROVIDER` | `local_openai_compatible` |
| `AI_BASE_URL` | `http://host.docker.internal:1234/v1` (LM Studio) |
| `AI_MODEL` | `qwen/qwen3-14b` |
| `AI_REQUEST_TIMEOUT_SECONDS` | `75.0` |
| `EMBEDDING_PROVIDER` | `local_openai_compatible` |
| `EMBEDDING_MODEL` | `text-embedding-nomic-embed-text-v1.5@q4_k_m` |
| `EMBEDDING_DIMENSIONS` | `768` |
| `EMBEDDING_TIMEOUT_SECONDS` | `60` |
| `EMBEDDING_FALLBACK_TO_HASH` | `true` |
| `HYPEREXTRACT_ENABLED` | `true` |
| `HYPEREXTRACT_PROVIDER` | `openai_compatible` |
| `HYPEREXTRACT_BASE_URL` | `http://host.docker.internal:1234/v1` |
| `HYPEREXTRACT_MODEL` | `qwen/qwen3-14b` |
| `HYPEREXTRACT_TIMEOUT_SECONDS` | `120.0` |
| `HYPEREXTRACT_RUN_IN_PIPELINE` | `true` |
| `SEARCH_MULTI_QUERY_MAX_VARIANTS` | `2` |
| `WORKER_FAST_CONCURRENCY` | `2` |
| Alembic head | `0055_fix_partitioned_job_references` |

### 1.3 Servicios Docker

`postgres`, `redis`, `backend`, `frontend`, `scheduler`, `watcher`,
`worker-fast`, `worker-heavy`, `worker-maintenance`, `worker-heavy-gpu-0`,
`worker-heavy-gpu-1`, `migrate`. Todos `Up` y `healthy` en el momento
de la medición.

## 2. Corpus BON PLA SOCIEDAD ANONIMA

28 documentos únicos, 1 duplicado (`datos.pdf`).

| Métrica | Valor |
|---|---:|
| Total registrados | 28 |
| Únicos (no duplicados) | 27 |
| Con OCR `text_search_ready` | 27 |
| Con embeddings `semantic_search_ready` | 27 |
| Marcados `needs_reembedding` | 0 |
| Marcados `needs_review` | 7 |
| Confianza OCR media (página) | 0,616 |
| Documentos con OCR bajo (< 0.5) | 5 |

### 2.1 Distribución por formato y clasificación

| Formato | Cuenta | Tipos documentales observados |
|---|---:|---|
| `.msg` | 7 | `email_exportado` (6), `email` (1) |
| `.xlsx` | 2 | `plano` (1), `excel` (1) |
| `.jpeg` | 2 | `presupuesto` (2) |
| `.pdf` | 16 | `albaran` (3), `hoja_confeccion` (5), `croquis_medida` (2), `croquis` (1), `pedido` (2), `orden_trabajo` (1), `desconocido` (2) |
| `.docx` | 1 | `croquis_medida` (1) |

Manifiesto anonimizado: `backend/tests/fixtures/minimax_m3_eval/manifest.sanitized.json`.

## 3. Conjunto dorado de preguntas

`backend/tests/fixtures/minimax_m3_eval/questions.json` define 12
escenarios, cada uno con:

- Documentos fuente permitidos (synthetic ID `BP-NNN`).
- Hechos obligatorios y prohibidos.
- Citas esperadas.
- Indicación de abstención.
- Latencia objetivo.
- Tipo de pregunta: exact / filename / synthesis / followup / no_evidence
  / low_ocr / injection / negative_permission / cache_repeat.

Los IDs sintéticos se mapean a los nombres reales en el manifiesto;
ninguna pregunta expone nombres comerciales en el artefacto.

## 4. Benchmark reproducible

### 4.1 Herramienta

`scripts/benchmark_ai_pipeline.py` ejecuta los 10 escenarios del
conjunto dorado (4 runs por escenario: 1 cold + 3 warm) contra la API
autenticada. Mide:

- `total_ms` (cierre del stream).
- `first_event_ms` (primer byte SSE legible).
- `first_delta_ms` (primer `delta` con texto).
- `time_to_end_ms` (evento `end`).
- `fallback`, `sources_count`, `confidence`, `model_name`.

Salida:

- Resumen tabular en stdout.
- `data/minimax-m3-performance/baseline-stream.json` con cada run.

### 4.2 Resultados baseline (FASE 0)

```
scenario                          runs   ok    p50ms    p95ms   fe_p95   fd_p95
--------------------------------------------------------------------------------
exact_identifier_3987                4    4    31365    33895    30865    31979
filename_query                       4    4    26147    27304    24049    25555
short_followup                       4    4    12224    12871    10075    11347
synthesis_two_docs                   4    4    53254    59297    48727    52056
fact_albaran_pair                    4    4    42174    48792    46137    47018
ayuda_aitor                          4    4    29987    31197    27585    29240
no_evidence                          4    4    32548    33094    31477    32155
low_ocr_awareness                    4    4    41508    50220    47440    48515
injection_attempt                    4    4    39889    50118    50100        0
greeting_factual                     4    4    27947    29643    25519    28921
```

Hallazgos clave:

1. **Ningún escenario cumple el objetivo de FASE 4** (`first_event_ms p95 <= 300 ms`). El menor es `short_followup` con 10 s; el peor `injection_attempt` con 50 s.
2. **`injection_attempt` siempre cae al fallback** (`fallback_count = 4`, `sources_count = 0` en las 4 ejecuciones). La heurística anti-inyección está rechazando incluso preguntas legítimas cuya formulación contiene la palabra "ignora".
3. **`no_evidence` tarda 30 s** pese a que el motor debería poder responder en milisegundos con la plantilla grounded. El LLM se invoca incluso cuando la caché semántica/exacta podría saltarse la generación.
4. **Latencias p95/p50 muy estables** entre runs (rango <10%): la mayor variabilidad está en el arranque del LLM, no en retrieval.
5. **Sigue sin haber caché-first en streaming**: la API actual escribe al final del stream pero no consulta al inicio.

### 4.3 Cómo reproducir

```bash
python scripts/benchmark_ai_pipeline.py \
  --warm-runs 3 \
  --output-json data/minimax-m3-performance/baseline-stream.json
```

Las dos ejecuciones con la misma semilla producen idéntico formato de
salida. El benchmark falla con exit code 1 si algún escenario tiene
cero ejecuciones exitosas.

## 5. Riesgos / bloqueos identificados

- El LLM local responde muy lento para preguntas factuales (qwen3-14b
  en LM Studio). FASE 4 (routing) y FASE 3 (reducir trabajo previo
  al LLM) son las palancas principales para bajar latencia.
- El rechazo de preguntas con "ignora" en `injection_attempt` indica
  un detector de inyección demasiado agresivo. FASE 5 ajustará el
  prompt y la heurística.
- La caché no se consulta al inicio. FASE 4 lo integrará.

## 6. Cambios locales preservados

`git status` antes de empezar: 14 archivos modificados, 0 destructivos.
Todos se conservan intactos. Las nuevas rutas añadidas están en
`scripts/`, `data/minimax-m3-performance/`,
`backend/tests/fixtures/minimax_m3_eval/` y `docs/`.
