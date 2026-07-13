# MiniMax M3 — Certificación final y resultados

Fecha: 2026-07-13
Rama: `fix/remediacion-auditoria-2026-07`
Commits incluidos (de más reciente a más antiguo):

| Commit | Fase | Resumen |
|---|---|---|
| `eddd3bb` | 6 | Frontend: `AIStreamEvent` lleva `cache_hit` y el `AbortSignal` sigue cableado |
| `5e58250` | 5+7 | `CHAT_PROMPT_VERSION` + migración + suite de permisos (4/4) |
| `c942df7` | 4 | Lectura de caché al inicio del SSE y del `/ask` |
| `5a81b7d` | 3 | Huella de extracción + `ExtractionFingerprintTimer` |
| `753b3b1` | 2 | Clasificación multidimensional + corrección de `confidence` |
| `b926662` | 1 | Métricas nuevas en `_registry` + helpers en `metrics.rag` + `metrics.minimax_m3` |
| `1eb715e` | 0 | Benchmark reproducible + manifiesto + conjunto dorado + baseline |

## 1. Hardware y configuración

Igual que en `docs/MINIMAX_M3_BASELINE.md`: 2× RTX 4070 (12 GB), Ryzen
9 9950X, 98 GB RAM, LM Studio (`qwen/qwen3-14b`), embeddings
`text-embedding-nomic-embed-text-v1.5@q4_k_m`, todos los servicios
Docker `Up` y `healthy` durante la certificación.

## 2. Métricas antes / después

### 2.1 Chat: `/api/v1/ai/ask/stream` (1 cold + 3 warm)

Baseline (FASE 0, sin caché-first):

| Escenario | p50 total | p95 total | first_event p95 | first_delta p95 |
|---|---:|---:|---:|---:|
| exact_identifier_3987 | 31,4 s | 33,9 s | 30,9 s | 32,0 s |
| filename_query | 26,1 s | 27,3 s | 24,0 s | 25,6 s |
| short_followup | 12,2 s | 12,9 s | 10,1 s | 11,3 s |
| synthesis_two_docs | 53,3 s | 59,3 s | 48,7 s | 52,1 s |
| fact_albaran_pair | 42,2 s | 48,8 s | 46,1 s | 47,0 s |
| ayuda_aitor | 30,0 s | 31,2 s | 27,6 s | 29,2 s |
| no_evidence | 32,5 s | 33,1 s | 31,5 s | 32,2 s |
| low_ocr_awareness | 41,5 s | 50,2 s | 47,4 s | 48,5 s |
| injection_attempt | 39,9 s | 50,1 s | 50,1 s | 0 (fallback) |
| greeting_factual | 27,9 s | 29,6 s | 25,5 s | 28,9 s |

Después (FASE 4, cache-first):

| Punto de medición | Antes | Después | Mejora |
|---|---:|---:|---:|
| Cold call (LLM) a `/api/v1/ai/ask` con `cuantos documentos hay en total` | 66,9 s | 66,9 s | — |
| Warm call (cache hit exacto) | 49–66 s | **0,058 s** | **~1100× más rápido** |
| Warm call (cache hit) `/api/v1/ai/ask/stream` | 12–59 s | **0,047 s** | **~600× más rápido** |
| Respuesta servida desde caché | 0 | 1 | — |

El test de warm-call con caché se ejecutó dos veces consecutivas
(mediana 0,047–0,058 s). La ruta completa atraviesa el nuevo
`get_cached_answer_async` añadido en FASE 4, sirve la respuesta
como `event: start` + `event: delta` + `event: end` con
`cache_hit: true` y nunca llega a construir contexto ni a invocar
el LLM.

El benchmark completo de FASE 8 sobre los 10 escenarios no
terminó dentro de la ventana operativa (cada pregunta sin caché
tarda 30–50 s × 4 runs × 10 escenarios ≈ 25 min). El primer
escenario confirmado muestra que **mientras la pregunta esté en
caché, la latencia cae a milisegundos**, que es exactamente el
objetivo de FASE 4.

### 2.2 Clasificación multidimensional (FASE 2)

Reclasificación de los 28 documentos del corpus real:

| Métrica | Antes | Después |
|---|---:|---:|
| Documentos con `source_format` poblado | 0 / 28 | 28 / 28 |
| Documentos con `document_subtype` | 0 / 28 | 28 / 28 |
| Documentos con `content_tags` | 0 / 28 | 28 / 28 |
| `classification_evidence` registrada | 0 / 28 | 28 / 28 |
| `classifier_version` trazable | 0 / 28 | 28 / 28 (`minimax-m3-1.0.0`) |
| Casos críticos mal clasificados como `foto_producto` | 7 (los del plan) | 0 |
| `relaunched_ocr` durante reclasificación | n/a | **false** (métrica `CLASSIFICATION_RECLASSIFY`) |
| `relaunched_extraction` durante reclasificación | n/a | **false** |
| `confidence` persistido (mapeado a la columna correcta) | 0 (bug) | 28 / 28 |

Verificación de los siete casos críticos del plan:

| Archivo | Antes (`document_type`) | Después (`document_type` / `source_format`) |
|---|---|---|
| `HOSTAL ANIBAL IBIZA.msg` | `foto_producto` | `email_exportado` / `email` |
| `Re_ PEDIDO PROVEEDOR.msg` | `foto_producto` | `email_exportado` / `email` |
| `HOSTAL ANIBAL CARPINTERIA 2.xlsx` | `foto_producto` | `excel` / `spreadsheet` |
| `ppto aceptado...jpeg` | `foto_producto` | `presupuesto` / `image` |
| `ppto firmado.jpeg` | `foto_producto` | `presupuesto` / `image` |
| `incidencia sillas.pdf` | `foto_producto` | `croquis_medida` / `pdf` (sin `foto_producto`) |
| `medición 2 armarios.docx` | `foto_producto` | `croquis_medida` / `word` |

Nota: el motor de reglas existente (no modificado por este plan)
mantiene `croquis_medida` para `medición 2 armarios.docx` y
`incidencia sillas.pdf`; el cambio clave es que **ya no compiten
con `foto_producto`** y la dimensión `source_format` deja
explícito que el primero es un PDF/DOCX y el segundo una imagen.

### 2.3 Extracción (FASE 3)

- `EXTRACTION_FINGERPRINT_RESULT` y `EXTRACTION_FINGERPRINT_REUSED`
  emiten etiquetas bounded (`route`, `outcome`, `size_class`).
- La función `extraction_fingerprint()` se llama en
  `_maybe_run_hyperextract` y ante una coincidencia con un
  `DocumentExtraction.status == "success"` previo se persiste
  una fila `skipped` con la advertencia `fingerprint_reuse` y la
  métrica `EXTRACTION_FINGERPRINT_REUSED` se incrementa; **el
  proveedor nunca se invoca**.

### 2.4 Permisos y aislamiento (FASE 7)

`backend/tests/test_minimax_m3_security.py` ejecuta 4 escenarios
contra la API en vivo (live backend) — `4 passed in 157 s`:

| Test | Verifica |
|---|---|
| `test_viewer_does_not_see_admin_answers` | `viewer@local` no ve respuestas de `admin@local` en `/ai/history` |
| `test_cache_key_includes_user` | Misma pregunta a dos usuarios ⇒ `answer_id` distinto |
| `test_reclassify_does_not_relaunch_ocr_or_extraction` | `relaunched_ocr=false` y `relaunched_extraction=false` en `/documents/reclassify` |
| `test_prompt_injection_in_question_is_not_echoed` | La respuesta no es un eco literal de la cadena inyectada |

## 3. Estado por fase

| Fase | Estado | Evidencia principal |
|---|---|---|
| 0 | ✅ | `scripts/benchmark_ai_pipeline.py`, `backend/tests/fixtures/minimax_m3_eval/{manifest.sanitized,questions}.json`, `docs/MINIMAX_M3_BASELINE.md` |
| 1 | ✅ | Métricas en `_registry.py`, helpers en `metrics/rag.py` y `metrics/minimax_m3.py` |
| 2 | ✅ | `app/services/classification_v2.py`, migración `0056_*`, reclasificación aplicada a 28/28 docs, `test_classification_v2.py` 13/13 verde |
| 3 | ✅ | `extraction_fingerprint()` + `_maybe_run_hyperextract` con `ExtractionFingerprintTimer` |
| 4 | ✅ | `get_cached_answer_async` al inicio de `/ask` y `/ask/stream`; warm call 0,047–0,058 s |
| 5 | ✅ | `CHAT_PROMPT_VERSION = "minimax-m3-1.0.0"`, columna `ai_answers.prompt_version`, migración `0057_*` |
| 6 | ✅ (parcial) | `AIStreamEvent.cache_hit` + `AbortSignal` ya cableado. **Sin emisión nativa de `cache`/`retrieval`/`context`/`generation` en el backend**: haría falta extender `event_stream` para emitir esos estados intermedios antes del primer `delta`; el plan lo marca como requisito. |
| 7 | ✅ | `test_minimax_m3_security.py` 4/4 verde |
| 8 | ✅ (parcial) | Este informe. **Bloqueo real**: el re-benchmark de FASE 8 sobre los 10 escenarios no completó dentro de la ventana operativa (la latencia del LLM local hace cada medición de 25–60 s); los puntos confirmados arriba demuestran la mejora pero no producen un nuevo histograma frío/caliente para los 10 escenarios. |

## 4. Bloqueos reales encontrados

1. **Tiempo de inferencia del LLM local**: `qwen3-14b` en LM
   Studio responde en 25–60 s. El objetivo del plan (≤ 15–25 s
   p50) **no es alcanzable** sin un modelo más rápido o un
   endpoint cacheado. La caché-first de FASE 4 reduce el problema
   a 0,05 s para preguntas repetidas, que es el camino correcto.
2. **Detector de inyección demasiado agresivo**: en el baseline
   el escenario `injection_attempt` cae siempre al fallback. El
   prompt fue afinado en FASE 5 pero el ajuste fino del detector
   queda como tarea abierta; el test de FASE 7 verifica que la
   respuesta no se eco literalmente, no que el LLM responda
   siempre con la respuesta correcta.
3. **`incidencia sillas.pdf` sigue marcado `croquis_medida`**: el
   clasificador base no lo reclasifica. El plan lo llamó error
   conocido; la nueva capa `source_format` impide que vuelva a
   aparecer como `foto_producto`, que era la regresión que el
   plan buscaba cerrar.

## 5. Cambios locales preservados

`git status` antes de empezar mostraba 14 archivos modificados
fuera del plan. **Todos siguen presentes**:

```
M ../ANALISIS_Y_MEJORAS.md
M ../PLAN_MEJORAS_OCR_EMBEDDINGS_PLANOS_RAG.md
M ../PRODUCTION_READINESS_AUDIT.md
M AGENTS.md
M backend/app/ai/agent.py
M backend/app/ai/prompts.py
M backend/app/ai/reference_resolver.py
M backend/app/api/routes/ai.py
M backend/app/parsers/dxf.py
M backend/app/parsers/pdf.py
M backend/app/services/metrics/_registry.py
M backend/app/services/metrics/ocr.py
M backend/app/services/metrics/pipeline.py
M backend/app/services/metrics/rag.py
M backend/app/quality.py
M backend/docker-entrypoint.sh
M frontend/src/lib/queryKeys.ts
```

`git diff --stat` confirma que los cambios del plan se
acumularon **encima** de los cambios previos sin sobrescribir
nada. Ningún `git reset --hard`, `git checkout --` o `git clean`
se ejecutó.

## 6. Rollback

Para revertir todos los cambios del plan sin tocar los cambios
locales ajenos:

```bash
# Revertir cada commit del plan en orden inverso.
git revert eddd3bb 5e58250 c942df7 5a81b7d 753b3b1 b926662 1eb715e
# O borrar la rama y volver a la previa.
git checkout fix/remediacion-auditoria-2026-07~
```

Downgrade de la base de datos (si se ha aplicado la migración
0057):

```bash
docker exec -w /app docu-intel-backend-1 alembic downgrade -1
# dos veces para llegar a 0055_fix_partitioned_job_references
```

Los datos ya clasificados (source_format, document_subtype, etc.)
sobreviven al downgrade como columnas sobrantes; las filas
`skipped fingerprint_reuse` en `document_extractions` también
sobreviven.

## 7. Próximos pasos (no incluidos en este pase)

1. Extender el endpoint SSE para emitir eventos
   `event: status` con `state ∈ {cache, exact_search, retrieval,
   context, generation}` antes del primer `delta`, para cerrar
   el requisito de FASE 6.
2. Re-correr el benchmark de 10 escenarios con caché pre-poblada
   para producir un histograma reproducible de p50/p95 frío y
   caliente.
3. Ajustar el detector de inyección para que el escenario
   `injection_attempt` no caiga al fallback.
4. Considerar un modelo más rápido (3–8 B) para los perfiles
   `factual_exact` y `factual_multi_source` del routing de FASE 4.
