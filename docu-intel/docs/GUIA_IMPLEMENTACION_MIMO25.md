# 1. Resumen ejecutivo

Guía operativa para que Mimo 2.5 corrija `docu-intel` en cambios pequeños, verificables y reversibles. Fecha de auditoría: 2026-07-10. Rama observada: `fix/remediacion-auditoria-2026-07`; commit base: `d7b458c`.

Estado: **NO APTO PARA PRODUCCIÓN**. Bloqueos confirmados: cuenta admin fija `anas@admin.com/123123123`; autorización aplicada después del top-k en búsqueda/RAG; herramientas IA estructuradas sin `AccessScope`; migración `0033` imposible con datos; downgrade Alembic roto; deriva 768/1024 en embeddings; BM25 con `db` indefinido; warmup OCR con `Path` no importado; cola Redis compartida con política de expulsión; 149 fallos pytest; lint frontend roto; umbrales de cobertura frontend incumplidos.

Objetivo de ejecución: primero impedir acceso indebido y pérdida de datos; después estabilizar esquema, vectorización, OCR, colas y RAG; cerrar con API, despliegue, frontend, pruebas y operación. Cada tarea: 15–90 min, un commit, máximo habitual de ocho archivos. Si una precondición o prueba de parada falla, Mimo debe detenerse, documentar evidencia y no improvisar.

Decisión de embeddings: fijar `ibm-granite/granite-embedding-311m-multilingual-r2`, 768 dimensiones, distancia coseno y revisión inmutable. Es multilingüe, incluye español y entrega vectores densos de 768 dimensiones según [model card oficial de IBM](https://huggingface.co/ibm-granite/granite-embedding-311m-multilingual-r2). No cambiar a `BAAI/bge-m3` sin migración completa: su configuración oficial declara `hidden_size=1024` ([config oficial](https://huggingface.co/BAAI/bge-m3/blob/main/config.json)).

## Convenciones para Mimo 2.5

- Estados: **FALLO CONFIRMADO**, **RIESGO PROBABLE**, **MEJORA RECOMENDADA**, **OPCIONAL**, **NO VERIFICADO**.
- No asumir que comentarios, tests antiguos o documentos describen comportamiento actual.
- Antes de editar: `git status --short`, `rg -n`, abrir símbolo completo, ejecutar test de caracterización.
- No borrar datos. Migraciones destructivas requieren backup verificado, tabla sombra y rollback ensayado.
- Mantener `BaseOCREngine.extract(image_path: Path) -> OCRResult`, firmas públicas `embed_many`/`search_*` y política sin hash fallback silencioso.
- No introducir dependencia sin `requirements.txt`, imagen Docker y test de importación.
- Mensaje de commit exactamente el indicado; no mezclar tareas.

# 2. Estado actual verificado

## Estructura y comandos oficiales

- Backend: `backend/app/`; FastAPI en `backend/app/main.py`; Celery en `backend/app/workers/`; OCR en `backend/app/ocr/`; IA/RAG en `backend/app/ai/` y `backend/app/services/`.
- Migraciones: `backend/alembic/versions/`, 44 revisiones lineales `0001`–`0044`.
- Frontend: `frontend/src/`, React/Vite/TanStack Query.
- Infra: `docker-compose.yml`, `docker-compose.prod.yml`, `backend/Dockerfile`, `backend/Dockerfile.gpu`, `frontend/Dockerfile`.
- CI oficial: `.github/workflows/ci.yml`.
- Backend oficial: `alembic upgrade head`; `ruff check app/`; `ruff format --check app/`; `mypy app/`; `pytest --cov=app --cov-report=term-missing --cov-fail-under=50`; `pytest -m contract -v`.
- Frontend oficial: `npm ci`; `npm run lint`; `npm run format:check`; `npm test`; `npm run build`.

## Resultado de validaciones 2026-07-10

| Validación | Resultado | Evidencia |
|---|---|---|
| `python -m compileall -q app` | PASS | Python 3.11.15, contenedor efímero, fuente `:ro`, pycache en `/tmp`. |
| `pytest -p no:cacheprovider` | FAIL | 1231 passed, 149 failed, 30 skipped, 11 errors, 67 warnings; 163.92 s. |
| Ruff | FAIL | 59 errores; incluye `app/services/bm25.py:401 F821 db`, `app/workers/celery_app.py:129 F821 Path`. |
| Ruff format | FAIL | 43 archivos requieren formato. |
| mypy | FAIL | 255 errores en 61 archivos; 235 archivos comprobados. |
| `npm run lint` | FAIL | 1 error, 28 warnings; hook condicional `frontend/src/pages/document/ExcelViewer.tsx:75`. |
| `npm run format:check` | FAIL | 136 archivos fuera de formato. |
| `npm test` | FAIL de gate | 20 archivos/130 tests pasan; cobertura global 11.37 %, umbrales por archivo incumplidos. |
| `npm run build` | PASS | 2018 módulos; chunk principal 429.56 kB; Chat 40.37 kB; lazy chunks presentes. |
| Compose local `config --quiet` | PASS | `.env` actual. |
| Compose prod `config --quiet` | PASS | `.env.production.example`. |
| Alembic fresh `upgrade head` | PASS | PostgreSQL 16 + pgvector efímero. |
| Alembic fresh `downgrade base` | FAIL | `0042` no puede quitar `documents.embedding_model_version`; vista recreada por downgrade `0044` depende de columna. |
| Alembic 0032 con fila histórica → head | FAIL | `0033`: `no partition of relation audit_logs found for row`. |
| Build Docker backend/frontend | NO VERIFICADO | Sin salida tras varios minutos; proceso detenido. Repetir en terminal con progreso `plain`. |

Limitación: herramientas CCE `context_search`, `expand_chunk`, `related_context`, `session_recall` y `record_decision` exigidas por `AGENTS.md` no estaban expuestas. Auditoría usó `rg`, lectura focalizada, tests y PostgreSQL/Docker efímeros. Marcar esta carencia en cualquier comparación posterior.

# 3. Fallos críticos

| ID | Estado | Bloquea producción | Fallo | Evidencia mínima |
|---|---|---:|---|---|
| C-01 | FALLO CONFIRMADO | Sí | Admin fijo con contraseña trivial creado al arranque. | `backend/app/database/init_db.py:10-31`. |
| C-02 | FALLO CONFIRMADO | Sí | Búsqueda semántica/híbrida filtra permisos después de top-k; fuga interna y starvation. | `search_service.py:416,503`; `routes/search.py:318`; `tenant_access.py:601`. |
| C-03 | FALLO CONFIRMADO | Sí | Herramientas IA de presupuestos/pedidos devuelven contexto sin `AccessScope`. | `backend/app/ai/context.py:140-340`. |
| C-04 | FALLO CONFIRMADO | Sí | `0033` copia antes de crear particiones; upgrade con una fila falla. | Ejecución PostgreSQL efímera; `0033...py:256-289`. |
| C-05 | FALLO CONFIRMADO | Sí | Tablas particionadas sin identity/sequence; FKs entrantes siguen tabla legacy; downgrade pierde escrituras. | `0033...py:218-309`. |
| C-06 | FALLO CONFIRMADO | Sí | Downgrade fresh falla entre `0044` y `0042`. | Error `DependentObjectsStillExist`. |
| C-07 | FALLO CONFIRMADO | Sí | Modelo/env 1024 contradice ORM/migración 768. | `config.py:256-263`, `.env*.example`, `models/document.py`, `0032`. |
| C-08 | FALLO CONFIRMADO | Sí | Redis broker/result/cache usa `allkeys-lru`; puede expulsar mensajes. | `docker-compose.prod.yml`. |
| C-09 | FALLO CONFIRMADO | Sí | BM25 falla al filtrar confianza por nombre `db` inexistente. | `backend/app/services/bm25.py:358-420`. |
| C-10 | FALLO CONFIRMADO | Sí | Warmup Celery no importa `Path`, no usa `preload_ocr_engine` y prueba archivo inválido. | `backend/app/workers/celery_app.py:80-143`. |
| C-11 | FALLO CONFIRMADO | Sí | Publicación de job no es atómica con commit; puede quedar `pending` sin tarea. | rutas de registro + `apply_async`. |
| C-12 | FALLO CONFIRMADO | Sí | Suite/CI no está verde: backend, lint, formato y cobertura frontend fallan. | Tabla de validaciones. |

# 4. Índice maestro de tareas

| ID | Fase | Prioridad | Tipo | Bloquea producción | Estimación | Dependencias | Commit |
|---|---|---|---|---:|---:|---|---|
| F0-01 | Seguridad | P0 | FALLO CONFIRMADO | Sí | 30 min | — | `fix(security): remove fixed bootstrap admin` |
| F0-02 | Seguridad | P0 | FALLO CONFIRMADO | Sí | 75 min | F0-01 | `fix(authz): compile complete document scope predicates` |
| F0-03 | Seguridad | P0 | FALLO CONFIRMADO | Sí | 90 min | F0-02 | `fix(authz): prefilter search before ranking` |
| F0-04 | Seguridad | P0 | FALLO CONFIRMADO | Sí | 75 min | F0-02 | `fix(ai): scope structured tools before retrieval` |
| F0-05 | Seguridad | P0 | FALLO CONFIRMADO | Sí | 45 min | F0-02 | `fix(authz): scope work items and comments` |
| F0-06 | Seguridad | P1 | RIESGO PROBABLE | Sí | 45 min | — | `fix(ingestion): validate untrusted relative paths` |
| F0-07 | Seguridad | P1 | MEJORA RECOMENDADA | No | 30 min | — | `fix(ops): require metrics token outside local` |
| F1-01 | Migraciones | P0 | FALLO CONFIRMADO | Sí | 60 min | F0 | `fix(migrations): create partitions before copy` |
| F1-02 | Migraciones | P0 | FALLO CONFIRMADO | Sí | 90 min | F1-01 | `fix(migrations): preserve ids defaults and job foreign keys` |
| F1-03 | Migraciones | P0 | FALLO CONFIRMADO | Sí | 75 min | F1-02 | `fix(migrations): make partition rollback data safe` |
| F1-04 | Migraciones | P0 | FALLO CONFIRMADO | Sí | 45 min | — | `fix(migrations): restore materialized view safely` |
| F1-05 | Migraciones | P1 | FALLO CONFIRMADO | Sí | 45 min | F1-04 | `fix(migrations): repair invoice downgrade chain` |
| F1-06 | Esquema | P1 | FALLO CONFIRMADO | Sí | 45 min | F1-01 | `fix(schema): align document block type constraint` |
| F1-07 | Esquema | P1 | MEJORA RECOMENDADA | Sí | 90 min | F1-05 | `refactor(money): migrate financial values to numeric` |
| F2-01 | Embeddings | P0 | FALLO CONFIRMADO | Sí | 45 min | F1 | `fix(embeddings): pin granite multilingual 768 profile` |
| F2-02 | Embeddings | P0 | FALLO CONFIRMADO | Sí | 45 min | F2-01 | `fix(embeddings): reject every runtime dimension mismatch` |
| F2-03 | Embeddings | P1 | FALLO CONFIRMADO | Sí | 30 min | F2-01 | `test(embeddings): lock query and passage roles` |
| F2-04 | Embeddings | P1 | MEJORA RECOMENDADA | No | 60 min | F2-01 | `fix(embeddings): retry remote provider with jitter` |
| F2-05 | Chunking | P1 | FALLO CONFIRMADO | No | 60 min | F2-01 | `fix(chunking): bound long text and split tables by row` |
| F2-06 | Reindexado | P0 | FALLO CONFIRMADO | Sí | 75 min | F2-01 | `fix(reindex): version and select embeddings deterministically` |
| F3-01 | OCR | P0 | FALLO CONFIRMADO | Sí | 45 min | F2 | `fix(ocr): execute real worker warmup` |
| F3-02 | OCR | P0 | FALLO CONFIRMADO | Sí | 75 min | F3-01 | `fix(ocr): remove non-cancellable init threads` |
| F3-03 | OCR | P1 | RIESGO PROBABLE | Sí | 60 min | F3-02 | `fix(ocr): serialize shared gpu inference` |
| F3-04 | OCR/PDF | P1 | FALLO CONFIRMADO | Sí | 75 min | F3-02 | `fix(pdf): score dpi ladder and clean renders` |
| F3-05 | OCR/PDF | P1 | FALLO CONFIRMADO | Sí | 60 min | F3-04 | `fix(pdf): validate text layer and confidence provenance` |
| F3-06 | OCR | P1 | FALLO CONFIRMADO | No | 30 min | F3-02 | `fix(ocr): reuse engine for page reprocessing` |
| F3-07 | Planos | P1 | FALLO CONFIRMADO | Sí | 90 min | F3-04 | `fix(plans): persist dpi and measure dimension geometry` |
| F3-08 | Extracción | P1 | FALLO CONFIRMADO | Sí | 75 min | F1-07 | `fix(extraction): stage business and plan replacements atomically` |
| F4-01 | Celery | P0 | FALLO CONFIRMADO | Sí | 60 min | F0 | `fix(queue): separate redis broker from cache` |
| F4-02 | Celery | P0 | FALLO CONFIRMADO | Sí | 45 min | F4-01 | `fix(celery): configure loss rejection visibility and memory` |
| F4-03 | Celery | P0 | FALLO CONFIRMADO | Sí | 90 min | F4-02 | `fix(queue): publish jobs through transactional outbox` |
| F4-04 | Celery | P1 | FALLO CONFIRMADO | Sí | 75 min | F4-03 | `fix(queue): requeue stale work and persist dead letters` |
| F4-05 | GPU | P0 | FALLO CONFIRMADO | Sí | 45 min | F3-03 | `fix(gpu): dedicate one workload per device` |
| F4-06 | Celery | P1 | FALLO CONFIRMADO | No | 45 min | F2-06 | `fix(schedule): run versioned reocr and reembed sweeps` |
| F5-01 | Búsqueda | P0 | FALLO CONFIRMADO | Sí | 60 min | F0-03 | `fix(search): execute bm25 filters in sql` |
| F5-02 | Ranking | P0 | FALLO CONFIRMADO | Sí | 45 min | F5-01 | `fix(search): preserve chunk identity in rrf` |
| F5-03 | Ranking | P1 | FALLO CONFIRMADO | No | 45 min | F5-02 | `fix(search): apply mmr before final limit` |
| F5-04 | RAG | P0 | FALLO CONFIRMADO | Sí | 75 min | F0-04,F5-02 | `fix(rag): preserve page confidence and citation provenance` |
| F5-05 | RAG | P1 | FALLO CONFIRMADO | Sí | 75 min | F1-07,F0-04 | `fix(rag): compute authorized aggregates in sql` |
| F5-06 | RAG | P1 | RIESGO PROBABLE | No | 45 min | F5-04 | `fix(ai): release db session before streaming` |
| F6-01 | API | P0 | FALLO CONFIRMADO | Sí | 75 min | F0-02 | `fix(api): paginate only authorized rows` |
| F6-02 | API | P1 | RIESGO PROBABLE | Sí | 60 min | F0-06 | `fix(upload): inspect office archives and macro formats` |
| F6-03 | API | P1 | MEJORA RECOMENDADA | No | 60 min | F1 | `fix(api): align schemas and generate openapi contract` |
| F6-04 | API | P1 | MEJORA RECOMENDADA | No | 30 min | F0-07 | `fix(api): gate demo seed and sensitive admin operations` |
| F6-05 | API | P2 | MEJORA RECOMENDADA | No | 45 min | F0 | `fix(api): normalize error and request correlation responses` |
| F7-01 | Docker | P0 | FALLO CONFIRMADO | Sí | 45 min | F1 | `fix(deploy): add migration gate and remove weak defaults` |
| F7-02 | Docker | P1 | FALLO CONFIRMADO | Sí | 45 min | F7-01 | `fix(health): add live and ready probes` |
| F7-03 | Docker | P1 | MEJORA RECOMENDADA | No | 45 min | F7-01 | `chore(images): pin runtime image versions` |
| F7-04 | Docker | P2 | MEJORA RECOMENDADA | No | 45 min | F7-02 | `chore(docker): reduce container privileges` |
| F7-05 | Backups | P1 | FALLO CONFIRMADO | Sí | 60 min | F7-01 | `fix(backups): expose freshness and restore evidence` |
| F8-01 | Frontend | P1 | FALLO CONFIRMADO | Sí | 30 min | F0 | `fix(frontend): register global unauthorized handler` |
| F8-02 | Frontend | P1 | FALLO CONFIRMADO | No | 30 min | — | `fix(frontend): restore lint and formatting gates` |
| F8-03 | Frontend | P1 | MEJORA RECOMENDADA | No | 75 min | F6-03 | `refactor(frontend): generate api types and query keys` |
| F8-04 | Frontend | P1 | FALLO CONFIRMADO | Sí | 75 min | F8-02 | `test(frontend): meet meaningful coverage gates` |
| F8-05 | Frontend | P1 | RIESGO PROBABLE | No | 45 min | — | `fix(chat): stop persisting sensitive transcripts locally` |
| F8-06 | Frontend | P2 | MEJORA RECOMENDADA | No | 90 min | F8-02 | `refactor(frontend): split remaining monoliths` |
| F9-01 | Tests | P0 | FALLO CONFIRMADO | Sí | 45 min | F0-F8 | `fix(test): install async plugin and isolate settings` |
| F9-02 | Tests | P0 | FALLO CONFIRMADO | Sí | 60 min | F2 | `test(vectors): remove all 1024 dimensional fixtures` |
| F9-03 | Tests | P0 | FALLO CONFIRMADO | Sí | 90 min | F1 | `test(migrations): exercise seeded upgrade and downgrade` |
| F9-04 | Tests | P1 | FALLO CONFIRMADO | Sí | 75 min | F3 | `test(ocr): restore deterministic golden fixtures` |
| F9-05 | Benchmark | P1 | MEJORA RECOMENDADA | No | F2,F5 | 90 min | `test(rag): add spanish retrieval benchmark` |
| F9-06 | E2E | P1 | MEJORA RECOMENDADA | No | 90 min | F7,F8 | `test(e2e): validate authorized happy and denial paths` |
| F10-01 | Observabilidad | P1 | FALLO CONFIRMADO | Sí | 60 min | F7-02 | `fix(ops): report dependency and backup readiness` |
| F10-02 | Observabilidad | P1 | MEJORA RECOMENDADA | No | 60 min | F4,F5 | `feat(metrics): add queue search and ocr alerts` |
| F10-03 | Observabilidad | P2 | MEJORA RECOMENDADA | No | 45 min | F6-05 | `feat(logging): propagate request document and job ids` |
| F10-04 | Backups | P0 | FALLO CONFIRMADO | Sí | 90 min | F7-05 | `test(backups): automate isolated restore drill` |
| F10-05 | Mantenimiento | P2 | MEJORA RECOMENDADA | No | 60 min | F10-01 | `docs(ops): define maintenance ownership and slo` |

# 5. Plan general por fases

1. Congelar despliegues; backup + restore aislado; ejecutar F0.
2. Reparar migraciones en PostgreSQL efímero y datos copiados; ejecutar F1.
3. Fijar contrato de embedding 768 y reindexado; ejecutar F2.
4. Estabilizar vida de modelos, PDF/OCR y persistencia; ejecutar F3.
5. Separar Redis, asegurar entrega/idempotencia y GPUs; ejecutar F4.
6. Aplicar permisos antes del ranking; corregir BM25/RRF/MMR/citas; ejecutar F5.
7. Cerrar paginación, uploads, contratos y errores API; ejecutar F6.
8. Introducir gate de migración/readiness y backups verificables; ejecutar F7.
9. Reparar gates frontend y contratos generados; ejecutar F8.
10. Volver verdes tests, benchmark y E2E; ejecutar F9.
11. Activar alertas, restore drill y mantenimiento; ejecutar F10.

No avanzar de fase con un P0 rojo. Excepción: F0-02 es dependencia compartida de F5/F6; debe quedar cerrado antes de ambos.

# 6. Fase 0 — Seguridad y contención

### F0-01 — Eliminar admin fijo de bootstrap

- **Ficha:** P0; FALLO CONFIRMADO; seguridad; bloquea producción: sí; 30 min.
- **Objetivo / impacto:** impedir acceso trivial. Problema: `_EXTRA_ADMINS` crea `anas@admin.com` con `123123123` en cada arranque.
- **Evidencia / localización:** `backend/app/database/init_db.py:10-31`, `_EXTRA_ADMINS`, `create_initial_admin`.
- **Comportamiento esperado:** solo `ADMIN_EMAIL`/`ADMIN_PASSWORD` válidos crean admin inicial; cuenta fija existente se desactiva mediante comando explícito y auditable, nunca se borra.
- **Antes de tocar:** consultar cuenta por email y contar auditorías/propiedad. Guardar salida sin hash. Si está en uso, detener y pedir propietario.
- **Modificar:** `app/database/init_db.py`, test correspondiente y comando administrativo nuevo si no existe. **No modificar:** usuarios ajenos ni migraciones.
- **Cambios exactos / decisión / compatibilidad:** eliminar lista fija; bootstrap idempotente; añadir `disable_legacy_bootstrap_admin --dry-run`; no rotar secretos ni borrar filas.
- **Pseudocódigo:** `if legacy and dry_run: print(id, active); elif confirmed: legacy.is_active=False; audit(...)`.
- **Tests:** arranque no crea email fijo; admin configurado se crea una vez; dry-run no escribe; desactivación escribe auditoría.
- **Comandos:** `pytest tests/test_security.py -k bootstrap -v`; `ruff check app/database/init_db.py`.
- **Aceptación / parada:** cero literal `123123123` en `rg`; parar si cuenta tiene dependencia no identificada.
- **Rollback / dependencias / commit:** revertir código reactiva solo bootstrap configurado, nunca cuenta fija. Dependencias: ninguna. Commit `fix(security): remove fixed bootstrap admin`.
- **Prompt Mimo:** “Implementa F0-01 únicamente. Caracteriza bootstrap, elimina credencial fija, añade desactivación dry-run y tests. No borres usuarios ni toques auth JWT. Detente si cuenta legacy tiene relaciones desconocidas.”

### F0-02 — Compilar predicados completos de acceso

- **Ficha:** P0; FALLO CONFIRMADO; autorización; bloquea: sí; 75 min.
- **Objetivo / impacto:** una sola política SQL equivalente a `metadata_allows_scope`; evita filtrado tardío y paginación incompleta.
- **Evidencia / localización:** `app/services/tenant_access.py:295-375,601-716`; `_build_access_subquery` omite tags denegados y tipos; rama `allow_unassigned_documents` no coincide con evaluación Python.
- **Esperado:** predicado SQL cubre hotel/cadena, asignación, cuarentena, tags, tipos, deny-by-default; función Python y SQL dan mismo resultado.
- **Antes:** generar matriz de 30 casos con `AccessScope` y metadata; test diferencial SQL/Python.
- **Modificar:** `tenant_access.py` + tests. **No modificar:** roles, defaults de negocio ni datos.
- **Cambios / decisiones:** exponer `document_access_predicate(scope)` reutilizable; `False` explícito para scope vacío; arrays JSON mediante operadores PostgreSQL y fallback SQLite solo para tests.
- **Pseudocódigo:** `allowed = base_assignment & ~denied_tags & allowed_types & quarantine_rule`.
- **Tests:** matriz, sin grupo, `allow_all_hotels`, denied tag, tipo no permitido, unassigned, quarantine; PostgreSQL real.
- **Comandos:** `pytest tests/test_tenant_access.py tests/test_tenant_deny_by_default.py -v`.
- **Aceptación / parada:** igualdad SQL/Python; parar si semántica de unassigned no está aprobada por producto.
- **Rollback / deps / commit:** mantener función Python como oráculo durante rollback. Depende F0-01. Commit `fix(authz): compile complete document scope predicates`.
- **Prompt Mimo:** “Implementa F0-02 sin cambiar reglas de negocio. Convierte `metadata_allows_scope` en predicado SQL completo, añade tests diferenciales PostgreSQL y conserva API pública.”

### F0-03 — Autorizar antes de top-k

- **Ficha:** P0; FALLO CONFIRMADO; seguridad/RAG; bloquea: sí; 90 min.
- **Objetivo / impacto:** ningún candidato no autorizado entra en vector/BM25/RRF/cache.
- **Evidencia:** `search_service.py:416-650`; `routes/search.py:208-242,318`; `PgvectorStore._search_postgres`; hoy `_cache_scope` solo cambia clave y rutas filtran después.
- **Esperado:** `AccessScope` llega a `search_text`, `search_semantic`, `search_hybrid`, BM25 y pgvector sin romper llamadas existentes; SQL filtra antes de `LIMIT`.
- **Antes:** test con >limit documentos ajenos mejor puntuados y uno permitido relevante.
- **Modificar:** search service, vector store, BM25, ruta, tests; máximo 6 archivos. **No modificar:** pesos RRF.
- **Cambios / compatibilidad:** parámetro keyword-only opcional `access_scope=None`; endpoints autenticados siempre lo pasan; llamadas internas IA también; cache guarda solo resultado autorizado.
- **Pseudocódigo:** `stmt = stmt.where(document_access_predicate(scope)).order_by(distance).limit(pool)`.
- **Tests:** starvation, caché por scope, dos usuarios, export CSV/JSON, semantic/hybrid/BM25.
- **Comandos:** `pytest tests/test_tenant_access.py tests/test_search_filters.py tests/test_backlog_sprints.py -k 'search or scope' -v`.
- **Aceptación / parada:** cero postfiltrado como control primario; parar si driver pgvector impide join y diseñar subquery de IDs.
- **Rollback / deps / commit:** flag temporal solo para rollback local, nunca producción. Depende F0-02. Commit `fix(authz): prefilter search before ranking`.
- **Prompt Mimo:** “Implementa F0-03. Propaga scope keyword-only, filtra SQL antes de ranking/limit/cache, conserva firmas compatibles y prueba starvation multitenant.”

### F0-04 — Autorizar herramientas estructuradas IA

- **Ficha:** P0; FALLO CONFIRMADO; seguridad IA; bloquea: sí; 75 min.
- **Objetivo:** impedir que números de presupuesto/pedido conocidos recuperen datos fuera de scope.
- **Evidencia:** `app/ai/context.py:140-340`, `collect_context`; `redact_context_items_for_scope:118` solo oculta precios y no retira documento no autorizado.
- **Esperado:** cada herramienta acepta scope, incorpora predicado SQL y devuelve `not_found` indistinguible de no autorizado.
- **Antes:** tests de budget/order/invoice/delivery/shipping con dos tenants.
- **Modificar:** `ai/context.py`, `tools/*.py` o `integration_tools/*.py`, tests; dividir si supera 8 archivos. **No modificar:** prompts hasta cerrar filtrado.
- **Cambios / decisión:** fail closed; no consultar primero y redactar después; IDs y filenames también sensibles.
- **Pseudocódigo:** `row = db.scalar(select(...).where(number==n, document_access_predicate(scope)))`.
- **Tests:** todas ramas estructuradas; sin scope en llamada interna debe fallar explícito salvo admin controlado.
- **Comandos:** `pytest tests/test_tenant_access.py tests/test_conversational_grounding.py -v`.
- **Aceptación / parada:** ninguna `ContextItem` ajena; parar si herramienta no tiene vínculo documental y definir ownership antes.
- **Rollback / deps / commit:** revertible sin migración. Depende F0-02. Commit `fix(ai): scope structured tools before retrieval`.
- **Prompt Mimo:** “Implementa F0-04 solo. Inventaría cada rama de `collect_context`, aplica scope en SQL, usa not-found uniforme y añade pruebas cross-tenant.”

### F0-05 — Proteger work items y comentarios

- **Ficha:** P0; FALLO CONFIRMADO; API; bloquea: sí; 45 min.
- **Objetivo:** usuarios solo leen/mutan work items cuyo documento pueden ver.
- **Evidencia:** `app/api/routes/professional_admin.py:41-115` lista, actualiza y comenta por rol, sin scope documental.
- **Esperado:** lista/join paginado autorizado; create/update/comment revalidan documento en transacción.
- **Antes:** test cross-tenant para GET/PATCH/POST comment.
- **Modificar:** ruta, tenant helper si preciso, tests. **No modificar:** permisos admin globales acordados.
- **Cambios:** resolver scope una vez; aplicar predicado antes de limit; 404 uniforme.
- **Pseudocódigo:** `select(WorkItem).join(Document).where(scope_predicate)`.
- **Tests / comandos:** `pytest tests/test_workflow_enhancements.py -k work_inbox -v`.
- **Aceptación / parada:** conteo y lista coinciden; parar si work item puede carecer de document_id y definir política.
- **Rollback / deps / commit:** sin migración; F0-02. Commit `fix(authz): scope work items and comments`.
- **Prompt Mimo:** “Implementa F0-05 aplicando el predicado compartido a work-items, mutaciones y comentarios. Prueba lectura y escritura cross-tenant.”

### F0-06 — Validar rutas relativas no confiables

- **Ficha:** P1; RIESGO PROBABLE; ingestión/ACL; bloquea: sí; 45 min.
- **Objetivo:** impedir rutas absolutas, `..`, ADS Windows o separadores ambiguos usados para reglas de carpeta.
- **Evidencia:** `app/api/routes/documents.py:40-127`; `BatchUploadItem.relative_path` llega a `source_path` y reglas de asignación.
- **Esperado:** normalización POSIX canónica; rechazo de escape/absoluta/drive; ACL no deriva de texto de cliente sin namespace confiable.
- **Antes:** caracterizar upload individual/batch y watcher.
- **Modificar:** schema/ruta/helper/tests. **No modificar:** ruta almacenada real ni resolver de descargas.
- **Cambios:** `normalize_untrusted_relative_path`; prefijo `upload/<user_id>/`; folder rules solo si `source_origin=watcher` o asignación explícita.
- **Pseudocódigo:** `PurePosixPath; reject(is_absolute or '..' in parts or ':' in first_part)`.
- **Tests / comandos:** traversal Unix/Windows, Unicode slash, path válido; `pytest tests/test_file_storage.py tests/test_mass_ingestion.py -v`.
- **Aceptación / parada:** ningún input controla hotel/cadena por path; parar si producto depende de carpetas subidas y pedir mapeo explícito.
- **Rollback / deps / commit:** mantener valor original en auditoría, no como ACL. Commit `fix(ingestion): validate untrusted relative paths`.
- **Prompt Mimo:** “Implementa F0-06. Trata relative_path como no confiable, normaliza sin tocar storage, desacopla ACL y añade tabla de tests Windows/Linux.”

### F0-07 — Autenticar métricas fuera de local

- **Ficha:** P1; MEJORA RECOMENDADA; operaciones; bloquea: no; 30 min.
- **Objetivo:** evitar exposición interna de nombres/colas cuando token vacío.
- **Evidencia:** `app/services/metrics/endpoint.py:191-199`; `metrics_token` default vacío; ejemplos no lo fijan.
- **Esperado:** staging/production rechaza arranque o `/metrics` si token ausente; local puede permitir explícitamente.
- **Antes:** test de config por environment.
- **Modificar:** config, endpoint, env examples, tests. **No modificar:** payload de métricas.
- **Cambios:** `METRICS_TOKEN` obligatorio no-local; comparación constante; documentar scraper header.
- **Pseudocódigo:** `if nonlocal and not token: raise ValueError`.
- **Tests / comandos:** `pytest tests/test_phase6_observability.py -k metrics -v`.
- **Aceptación / parada:** 401 sin token y 200 con token; parar si Prometheus actual no puede enviar header y usar red dedicada temporal.
- **Rollback / deps / commit:** variable feature flag solo una release. Commit `fix(ops): require metrics token outside local`.
- **Prompt Mimo:** “Implementa F0-07 sin cambiar nombres de métricas. Haz token obligatorio no-local, comparación segura, ejemplos y tests.”

# 7. Fase 1 — Migraciones y esquema

### F1-01 — Crear particiones antes de copiar

- **Ficha:** P0; FALLO CONFIRMADO; migración; bloquea: sí; 60 min.
- **Objetivo:** permitir 0032→head con datos históricos.
- **Evidencia:** `alembic/versions/0033_partition_audit_and_jobs.py:249-289`; prueba real falla en `INSERT audit_logs` antes de `_create_monthly_partitions`.
- **Esperado:** partición default temporal o todas particiones necesarias creadas antes de copiar; fechas históricas preservadas.
- **Antes:** dump; test con filas de hace 24 meses, actual y futuro; `alembic upgrade 0032`.
- **Modificar:** 0033 solo si aún no desplegada; si desplegada parcialmente, nueva 0045 reparadora + test. **No modificar:** revisión aplicada en producción sin decisión operatoria.
- **Cambios / decisión:** detectar estado; crear particiones para min/max histórico más default; copiar; validar counts/checksum; retirar default solo si vacía.
- **Pseudocódigo:** `bounds=SELECT date_trunc(min/max); create range; INSERT; assert count`.
- **Tests / comandos:** ciclo PostgreSQL efímero seeded; `alembic upgrade 0032 && seed && alembic upgrade head`.
- **Aceptación / parada:** conteos idénticos; parar ante fila fuera de rango o estado parcial y conservar legacy.
- **Rollback / deps / commit:** no borrar `_legacy`; F0 cerrado. Commit `fix(migrations): create partitions before copy`.
- **Prompt Mimo:** “Implementa F1-01 con test PostgreSQL real. Crea particiones antes de INSERT, cubre histórico/futuro, valida conteos y no borres legacy.”

### F1-02 — IDs, ORM y FKs de particionadas

- **Ficha:** P0; FALLO CONFIRMADO; esquema; bloquea: sí; 90 min.
- **Objetivo:** inserts ORM funcionales y relaciones apuntando a tabla nueva.
- **Evidencia:** `0033:218-245` usa `id INTEGER NOT NULL` sin default; PK DB compuesta vs ORM simple; FKs `watched_files.job_id`/`ingestion_events.job_id` siguen renombrado legacy.
- **Esperado:** sequence/identity propia o conservada; invariantes de unicidad documentadas; FKs recreadas a nueva tabla; insert sin id funciona.
- **Antes:** consultar `pg_get_serial_sequence`, `pg_constraint`, `information_schema`; test de relaciones.
- **Modificar:** migración reparadora, modelos si se adopta PK compuesta, tests. **No modificar:** IDs existentes.
- **Cambios / decisión:** preferir sequence global por parent y `DEFAULT nextval`; mantener identidad lógica `id` y uniqueness global mediante allocator; recrear FKs con validación posterior.
- **Pseudocódigo:** `CREATE SEQUENCE; setval(max); ALTER id SET DEFAULT; DROP/ADD FK NOT VALID; VALIDATE`.
- **Tests:** insertar AuditLog/ExtractionJob; watcher/job/event round-trip; delete cascades; IDs únicos entre meses.
- **Comandos:** SQL catálogo + `pytest tests/test_mass_ingestion.py tests/test_phase5_operations.py -v`.
- **Aceptación / parada:** ORM insert y relaciones pasan; parar si Postgres exige rediseño PK que rompe API y crear ADR.
- **Rollback / deps / commit:** backup + legacy intacta; depende F1-01. Commit `fix(migrations): preserve ids defaults and job foreign keys`.
- **Prompt Mimo:** “Implementa F1-02. Inspecciona catálogo tras 0033, restaura default de IDs y FKs entrantes, prueba inserts ORM y no reasignes IDs.”

### F1-03 — Rollback sin pérdida de datos

- **Ficha:** P0; FALLO CONFIRMADO; migración; bloquea: sí; 75 min.
- **Objetivo:** downgrade no descarta escrituras posteriores.
- **Evidencia:** `0033:293-309` declara que pierde datos y restaura snapshot legacy.
- **Esperado:** rollback copia delta a tabla compatible o se marca irreversible con procedimiento restore explícito; nunca `DROP` silencioso.
- **Antes:** seed pre-upgrade, upgrade, seed post-upgrade, downgrade en copia.
- **Modificar:** 0033/nueva revisión, runbook, tests. **No modificar:** backup real.
- **Cambios / decisión:** opción preferida: reconstruir tabla no particionada sombra, copiar todo, validar, rename atómico; no usar legacy estática.
- **Pseudocódigo:** `CREATE audit_logs_rollback LIKE legacy; INSERT current; validate; swap`.
- **Tests / comandos:** conteo + hash de IDs antes/después; `alembic downgrade 0032`.
- **Aceptación / parada:** todas filas pre/post presentes; parar si FKs impiden swap y usar restore drill.
- **Rollback / deps / commit:** backup obligatorio; F1-02. Commit `fix(migrations): make partition rollback data safe`.
- **Prompt Mimo:** “Implementa F1-03 como rollback data-safe en PostgreSQL. Prueba filas escritas después del upgrade; prohíbe DROP antes de validar copia.”

### F1-04 — Reparar 0044/0042

- **Ficha:** P0; FALLO CONFIRMADO; Alembic; bloquea: sí; 45 min.
- **Objetivo:** ciclo fresh head→base→head completo.
- **Evidencia:** downgrade `0044` recrea `mv_active_documents AS SELECT *`; downgrade `0042` intenta quitar columnas incluidas y falla.
- **Esperado:** vista recreada con definición histórica exacta o retirada antes de 0042; downgrade simétrico.
- **Antes:** extraer definición original en `0037_search_performance_indexes.py`.
- **Modificar:** `0044_drop_mv_active_documents.py`, tests. **No modificar:** vista productiva sin backup.
- **Cambios:** recrear columnas explícitas originales; dependencia/orden seguro; test de catálogo.
- **Pseudocódigo:** `downgrade 0044: CREATE MATERIALIZED VIEW ... lista histórica, nunca SELECT *`.
- **Tests / comandos:** ciclo Alembic fresh completo en pgvector:pg16.
- **Aceptación / parada:** tres etapas pasan; parar si 0044 ya aplicada con consumidores de vista y medir uso.
- **Rollback / deps / commit:** sin datos de negocio; commit `fix(migrations): restore materialized view safely`.
- **Prompt Mimo:** “Implementa F1-04. Restaura definición exacta de vista, elimina SELECT *, añade ciclo head/base/head y no uses CASCADE como parche.”

### F1-05 — Cadena fiscal de facturas

- **Ficha:** P1; FALLO CONFIRMADO; Alembic; bloquea: sí; 45 min.
- **Objetivo:** downgrades 0043→0033 sin doble drop/truncación.
- **Evidencia:** 0034 upgrade `pass` pero downgrade borra columnas añadidas en 0040; 0043 declara existing_type 32 aunque 0040 crea 50.
- **Esperado:** cada revisión revierte solo lo que creó; ancho 50→32 solo con precheck y política.
- **Antes:** test con NIF de >32 chars si permitido; inspeccionar historial aplicado.
- **Modificar:** 0034/0040/0043 o revisión correctora, tests. **No modificar:** valores fiscales.
- **Cambios:** quitar drops de 0034; exactitud `existing_type`; downgrade destructivo requiere `length <=32` o parada.
- **Pseudocódigo:** `SELECT count(*) WHERE length>32; if >0 raise`.
- **Tests / comandos:** upgrades/downgrades por frontera con fila fiscal.
- **Aceptación / parada:** no UndefinedColumn ni truncación; parar ante valor largo.
- **Rollback / deps / commit:** backup invoices; F1-04. Commit `fix(migrations): repair invoice downgrade chain`.
- **Prompt Mimo:** “Implementa F1-05. Haz cada downgrade simétrico, añade precheck de ancho y prueba datos fiscales; nunca trunques.”

### F1-06 — Alinear block types

- **Ficha:** P1; FALLO CONFIRMADO; esquema OCR; bloquea: sí; 45 min.
- **Objetivo:** ORM/PP-Structure no produzcan valores rechazados por CHECK.
- **Evidencia:** `0032` limita tipos; `app/models/document.py` acepta además `doc_title`, `reference`, `seal`, `table_title` y otros.
- **Esperado:** enum/constraint único compartido y migración aditiva.
- **Antes:** `SELECT block_type,count(*)`; listar outputs de adaptadores.
- **Modificar:** constante central, modelo, migración, tests. **No modificar:** valores existentes.
- **Cambios:** fuente única; CHECK con lista completa; desconocido se mapea a `text` con métrica, no inventa valor.
- **Pseudocódigo:** `BLOCK_TYPES=frozenset(...); validates -> raise`.
- **Tests / comandos:** insert de cada valor; PP fixture; `pytest tests/test_pp_structure.py`.
- **Aceptación / parada:** lista ORM=DB=parser; parar ante tipo sin semántica definida.
- **Rollback / deps / commit:** ampliación reversible solo si no hay nuevos valores. Commit `fix(schema): align document block type constraint`.
- **Prompt Mimo:** “Implementa F1-06 con fuente única de block types, migración CHECK y pruebas de todos los tipos de PP-Structure.”

### F1-07 — Dinero exacto

- **Ficha:** P1; MEJORA RECOMENDADA; esquema/negocio; bloquea: sí antes de agregaciones; 90 min.
- **Objetivo:** eliminar errores binarios en presupuestos, pedidos, facturas, líneas y conciliación.
- **Evidencia:** `app/models/professional.py` usa `Float`; extracción usa `float` y sumas Python.
- **Esperado:** `Numeric(18,2)` o escala por campo; `Decimal` extremo a extremo; JSON serializa string/decimal acordado.
- **Antes:** inventario completo `rg 'Float|float'`; muestras con 0.1+0.2, moneda y redondeo IVA.
- **Modificar:** modelos, schemas, extracción, migración, tests; dividir en dos commits si >8 archivos, comenzando esquema. **No modificar:** redondeo legal sin decisión.
- **Cambios:** migración `USING round(col::numeric,2)` con reporte de delta; política `ROUND_HALF_UP`; backfill validado.
- **Pseudocódigo:** `Decimal(raw).quantize(Decimal('0.01'), ROUND_HALF_UP)`.
- **Tests / comandos:** totales, IVA, conciliación, JSON, migration delta; PostgreSQL.
- **Aceptación / parada:** delta reportado = esperado; parar ante precisión >2 significativa.
- **Rollback / deps / commit:** backup tablas financieras; F1-05. Commit `refactor(money): migrate financial values to numeric`.
- **Prompt Mimo:** “Implementa F1-07 en alcance máximo 8 archivos. Migra dinero a Numeric/Decimal con reporte de delta, política explícita y tests; no redondees silenciosamente.”

# 8. Fase 2 — Embeddings y pgvector

### F2-01 — Perfil único Granite 768

- **Ficha:** P0; FALLO CONFIRMADO; embeddings; bloquea: sí; 45 min.
- **Objetivo:** un contrato modelo/revisión/dimensión/distancia.
- **Evidencia:** `config.py:256-263` mezcla bge-m3/768 y Granite local; `.env.example:72-78` y production declaran bge-m3/1024; ORM y 0032 son 768.
- **Esperado:** proveedor local sentence-transformers, Granite R2, 768, cosine; revisión SHA inmutable registrada en `embedding_model_version`.
- **Antes:** confirmar disponibilidad/licencia/cache y SHA oficial; este SHA está **NO VERIFICADO**.
- **Modificar:** config defaults, env examples, docs de settings, tests. **No modificar:** vectores existentes hasta F2-06.
- **Cambios:** validar combinación modelo/dim; startup falla por perfil incoherente; versión=`repo@sha`.
- **Pseudocódigo:** `EmbeddingProfile(model, revision, dimensions=768, distance='cosine')`.
- **Tests / comandos:** settings local/prod; vector length; `pytest tests/test_embeddings_provider.py -v`.
- **Aceptación / parada:** ningún 1024 activo en configs; parar si modelo descargado no coincide revisión.
- **Rollback / deps / commit:** conservar índice anterior hasta reembed validado. F1. Commit `fix(embeddings): pin granite multilingual 768 profile`.
- **Prompt Mimo:** “Implementa F2-01. Fija Granite multilingual R2 768/cosine con revision obligatoria, alinea ejemplos y falla en startup ante deriva. No reembebas aún.”

### F2-02 — Fallar ante cualquier mismatch

- **Ficha:** P0; FALLO CONFIRMADO; vector; bloquea: sí; 45 min.
- **Objetivo:** cero padding/truncado o comparación parcial en runtime.
- **Evidencia:** `embeddings.py:679 cosine_similarity` usa longitud mínima; `coerce_embedding_dimensions:718` permite flag de coerción; pgvector espera 768.
- **Esperado:** igualdad exacta en proveedor, batch, cache, cosine y SQL; migración offline separada.
- **Antes:** localizar usos del flag y datos con dimensiones inválidas.
- **Modificar:** embeddings, vector store, config, tests. **No modificar:** firma pública `embed_many`.
- **Cambios:** retirar coerción runtime; excepción con expected/actual/model; herramienta offline puede aceptar flag explícito.
- **Pseudocódigo:** `if len(v)!=expected: raise EmbeddingDimensionError(...)`.
- **Tests / comandos:** unitarios 767/768/1024; `pytest tests/test_embedding_dimensions.py tests/test_vector_store.py -v`.
- **Aceptación / parada:** no `min(len(...))`; parar si hay vectores inválidos y ejecutar inventario antes.
- **Rollback / deps / commit:** feature flag solo CLI de migración. F2-01. Commit `fix(embeddings): reject every runtime dimension mismatch`.
- **Prompt Mimo:** “Implementa F2-02 manteniendo APIs públicas. Rechaza mismatch en todas las rutas y mueve coerción a herramienta offline explícita.”

### F2-03 — Bloquear roles query/passage

- **Ficha:** P1; FALLO CONFIRMADO parcialmente corregido; tests; bloquea: sí; 30 min.
- **Objetivo:** preservar `query:` en consulta y `passage:` en indexado.
- **Evidencia:** `embed_query_text:220` usa cliente local; `embed_many:263` passage; tests actuales incluyen expectativa antigua 1024.
- **Esperado:** tests espía sobre texto real enviado al modelo; OpenAI-compatible sin prompts se mantiene neutro.
- **Antes:** revisar prompts soportados por revisión Granite.
- **Modificar:** tests y quizá helper de perfil. **No modificar:** firma `embed_many`.
- **Cambios:** parametrizar proveedor simétrico/asimétrico; registrar role en cache key ya existente.
- **Pseudocódigo:** `client.embed_query('hola') -> encode('query: hola')`.
- **Tests / comandos:** `pytest tests/test_local_embedding_reranker.py tests/test_phase3_ai_search.py -k query -v`.
- **Aceptación / parada:** index y query usan roles distintos; parar si model card/revisión no define prompts y validar recall A/B.
- **Rollback / deps / commit:** F2-01. Commit `test(embeddings): lock query and passage roles`.
- **Prompt Mimo:** “Implementa F2-03 como tests de comportamiento, no de implementación. Verifica texto enviado y cache role; elimina expectativas 1024.”

### F2-04 — Reintentos del proveedor remoto

- **Ficha:** P1; MEJORA RECOMENDADA; resiliencia; bloquea: no; 60 min.
- **Objetivo:** tolerar 429/5xx/timeouts sin fallback hash.
- **Evidencia:** `OpenAICompatibleEmbeddingClient:91` tiene breaker pero una sola petición.
- **Esperado:** máximo 3 intentos; backoff exponencial+jitter; `Retry-After`; no retry 4xx salvo 408/409/429; breaker cuenta operación final.
- **Antes:** test con `httpx.MockTransport` y reloj inyectable.
- **Modificar:** embeddings, config, tests; sin dependencia nueva.
- **Cambios:** helper común retry; timeout connect/read explícito; métricas intentos.
- **Pseudocódigo:** `delay=min(cap,base*2**n)+rng.uniform(0,jitter)`.
- **Tests / comandos:** 500→200, timeout→200, 400 sin retry, breaker; tests embedding.
- **Aceptación / parada:** latencia acotada; parar si endpoint no es idempotente (embeddings sí).
- **Rollback / deps / commit:** flags attempts=1. F2-01. Commit `fix(embeddings): retry remote provider with jitter`.
- **Prompt Mimo:** “Implementa F2-04 con reloj/RNG inyectables, 3 intentos acotados y sin hash fallback. Prueba Retry-After y breaker.”

### F2-05 — Limitar chunks largos y tablas

- **Ficha:** P1; FALLO CONFIRMADO; chunking; bloquea: no; 60 min.
- **Objetivo:** ningún chunk supera tope; tablas se parten por fila conservando cabecera.
- **Evidencia:** `_split_oversized_sentence:228` no se usa; `_emit_table:241` conserva tabla ilimitada; `_split_table_block:134` no está conectado a `build_chunks:336`.
- **Esperado:** frases largas se cortan por tokens/palabras; tablas Markdown/alineadas se segmentan por filas; no mezclar páginas.
- **Antes:** fixtures 2k palabras sin puntuación y tabla 500 filas.
- **Modificar:** chunking + tests. **No modificar:** metadato prepend ni interfaz Chunk.
- **Cambios:** conectar helpers; repetir cabecera; overlap solo texto, no duplicar filas salvo header.
- **Pseudocódigo:** `for row_group in pack(rows,max_words-header): emit(header+group)`.
- **Tests / comandos:** `pytest tests/test_chunking.py -v`.
- **Aceptación / parada:** `word_count<=max_words` salvo metadata documentada; parar si una sola celda excede y aplicar split con marcador.
- **Rollback / deps / commit:** reindex necesario, F2-01. Commit `fix(chunking): bound long text and split tables by row`.
- **Prompt Mimo:** “Implementa F2-05 conectando helpers muertos, límites duros y filas de tabla. Prueba frases gigantes y tablas sin mezclar páginas.”

### F2-06 — Reindexado versionado y finito

- **Ficha:** P0; FALLO CONFIRMADO; reindexado; bloquea: sí; 75 min.
- **Objetivo:** seleccionar solo documentos desactualizados y escribir metadata completa.
- **Evidencia:** `reembed_document:170` no actualiza model version/chunk_type/token_count; `_select_reembed_candidates:18` incluye cualquier confianza no nula; no selecciona version mismatch; `needs_reembedding` casi no se establece.
- **Esperado:** candidatos por flag, vector nulo o versión distinta; baja confianza por `< threshold`; cada éxito sale del conjunto.
- **Antes:** test de dos ticks consecutivos; inventario por versión.
- **Modificar:** pipeline, embedding task, config, tests. **No modificar:** OCR en esta tarea.
- **Cambios:** transacción por documento; guardar version/provider/dimension/token_count; fallo conserva versión anterior y flag.
- **Pseudocódigo:** `WHERE needs OR chunk.embedding IS NULL OR version!=target OR confidence<threshold`.
- **Tests / comandos:** `pytest tests/test_reembed_document.py tests/test_reembed_pending_task.py -v`.
- **Aceptación / parada:** segundo tick procesa 0; parar si cobertura de chunks no coincide documento y reparar antes.
- **Rollback / deps / commit:** conservar chunks antiguos hasta swap; F2-01/02. Commit `fix(reindex): version and select embeddings deterministically`.
- **Prompt Mimo:** “Implementa F2-06. Corrige selección OR, versiona todo, swap transaccional y prueba que segundo tick es no-op.”

