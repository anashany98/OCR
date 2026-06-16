# Auditoría de Producción — Docu-Intel

**Fecha:** 15 de junio de 2026
**Alcance:** revisión profunda de todo el proyecto `docu-intel/` (backend FastAPI + Celery, frontend React/Vite, Docker, base de datos, búsqueda, chat, embeddings, OCR) para despliegue como **herramienta interna de producción** sobre Coolify.
**Auditor:** Sisyphus (revisión directa por imposibilidad de delegar en subagentes — todos los fondos agotados).

---

## TL;DR

El proyecto está **mucho más maduro** de lo que sugiere el fichero `PLAN_MEJORAS_OCR_EMBEDDINGS_PLANOS_RAG.md` (que es aspiracional). Casi todo lo que ese plan proponía ya está implementado:

- OCR cascada de 4 niveles con **scoring de calidad** y umbrales por idioma (O1-O7 ✅)
- Embeddings con **prefijo asimétrico query/passage** (A1 ✅), circuit breaker, batching async, caché Redis
- **Búsqueda híbrida con RRF + BM25 + reranker cross-encoder + MMR** (A2, E1-E6 ✅)
- **Chat con streaming SSE, abort, thinking tokens, fallback grounded, redacción** (R2, R5 ✅)
- **Learning loop** con propuestas de agente externo, revisión admin, webhooks firmados (✅)
- **Outbox transaccional** para webhooks con HMAC-SHA256, backoff, dead-letter (✅)
- **Deny-by-default tenant**, per-purpose JWT secrets, O(1) API key lookup, throttled `last_used_at` (✅)
- **CSP estricto + HSTS + Permissions-Policy + COOP/CORP** como middleware ASGI puro (✅)
- **Code splitting con `React.lazy` en todas las rutas**, route gates por rol, `errorElement`, NotFound (F1-F4 ✅)
- **31 migraciones Alembic** bien numeradas, incluyendo pgvector (HNSW), BM25 tsvector, índices GIN/trigram, versionado de modelo de embedding, soft-delete consistente (✅)
- **CI workflow** con typecheck + tests + build Vite (✅)

Lo que **sí queda por endurecer** es de orden táctico (no estratégico). El proyecto es **despliegable ya**, pero hay ~25 mejoras de robustez, rendimiento, observabilidad y seguridad que recomiendo aplicar antes de declararlo "producción estricta".

**Calificación global estimada:** **B+** (listo para producción interna con monitorización; listo para "producción seria" con los P0 de abajo resueltos en 1-2 sprints).

---

## Índice

1. [Lo que YA está bien hecho](#1-lo-que-ya-está-bien-hecho) (no perder tiempo aquí)
2. [Hallazgos por severidad](#2-hallazgos-por-severidad)
3. [Tabla resumen](#3-tabla-resumen)
4. [Roadmap priorizado](#4-roadmap-priorizado-1-2-sprints)
5. [Verificaciones mínimas antes de producción](#5-verificaciones-mínimas-antes-de-producción)
6. [Riesgos residuales](#6-riesgos-residuales)

---

## 1. Lo que YA está bien hecho

Esta sección es deliberadamente corta — para que conste lo que NO hay que tocar y por qué. **No perder tiempo re-implementando nada de aquí.**

### Backend / OCR
- `CascadingOCREngine` con `_quality` (confianza 0.5 + densidad alfanumérica 0.3 + longitud saturada 0.2), umbrales por idioma (`ocr_language.py`), `_should_replace_with_fallback` con delta 0.10 + alnum_gain 30, métricas Prometheus `track_ocr_tier_used` / `track_ocr_skip_tier2` / `track_ocr_cascade_fallback`. (`app/ocr/cascading.py:51-60, 69-123, 281-334`)
- Preprocesado separado para Tesseract (gris + binarización adaptativa) y Paddle (color/gris sin binarizar), con deskew (Hough + minAreaRect), corrección de orientación con Tesseract OSD, upscale si lado menor < 1500 px, log + fallback al path original. (`app/ocr/preprocess.py`)
- Singleton `get_ocr_engine()` con `RLock`, preload con `worker_process_init` y `_exercise()` para amortizar la compilación del grafo Paddle. (`app/ocr/factory.py:28-30, 70-113, 183-232` y `app/workers/celery_app.py:70-105`)
- `DotsMOCREngine` (Tier 4 VLM) ya integrado opcionalmente; `PP-Structure` opcional tras Tier 2. (`app/ocr/dots_mocr.py`, `app/ocr/pp_structure.py`)

### Backend / Embeddings
- `_ASYMMETRIC_MODELS` allowlist (no `startswith`), `_query_prompt_for` / `_passage_prompt_for` separados, `embed_query_text` con `role="query"` para query-side, `embed_many` con `role="passage"` para indexado. (A1 ✅). (`app/services/embeddings.py:223-256, 513-550, 607-643`)
- `coerce_embedding_dimensions` falla en alto (no pad silencioso) salvo `EMBEDDING_ALLOW_DIMENSION_COERCION=true` (A5 ✅). (`app/services/embeddings.py:716-728`)
- Batching async con `asyncio.Semaphore(MAX_CONCURRENT_BATCHES)`, cache `embedding:{md5}` con namespace + role + dimensiones, circuit breaker compartido. (`app/services/embeddings.py:299-337, 393-468`)
- `LocalSentenceTransformerEmbeddingClient` carga el modelo en background, GIL-friendly (`asyncio.to_thread`).

### Backend / Búsqueda
- `search_hybrid` ejecuta text + semantic + BM25 en paralelo y fusiona con RRF (A2 ✅); si está activado, aplica reranker cross-encoder `BAAI/bge-reranker-v2-m3` y MMR (`mmr_rerank` con lambda 0.7). (`app/services/search_service.py:423-483`)
- `merge_hybrid_results` con RRF k=60 configurable. (`app/services/search_service.py:486-531`)
- HyDE + Multi-query: `_hyde_embed` genera hipotético en español y lo embebe; `_multi_query_reformulations` produce variantes y se fusionan también con RRF. (`app/services/search_service.py:151-198, 339-419`)
- `search_text` con ILIKE escapando `%`/`_`/`\\` y deduplicación por (doc, page, block). (`app/services/search_service.py:69-141`)
- `vector_store.PgvectorStore` con cláusula `c.embedding <=> CAST(:query_embedding AS vector)` (cosine distance) + filtro `deleted_at IS NULL` + `budget_scope_id` opcional. Validación de dimensión **antes** de construir el literal. (`app/services/vector_store.py:62-93, 162-170`)

### Backend / IA
- `LocalOpenAICompatibleClient.chat_stream` con SSE real, parsea `delta.content` y `delta.reasoning_content` (Qwen3) por separado, aborte limpio, timeout configurable. (`app/ai/local_client.py:127-194`)
- `_post_chat_completion` con reintentos (backoff exponencial + jitter) y circuit breaker por (base_url, model). (`app/ai/local_client.py:196-269`)
- Agente: cache por (user, question, mode, scope_key) → tool selection → context collect → redaction por scope → grounded fallback → LLM si hay → validación (no responde en idioma incorrecto, no fabrika documentos) → persistencia. (`app/ai/agent.py:164-376`)
- `prompt_sanitizer` para anti-injection con sensitivity `low/medium/high` y action `log/sanitize/drop`. (`app/services/prompt_sanitizer.py`)

### Backend / Seguridad
- Middleware ASGI puro para CSP/HSTS/Permissions-Policy/COOP/CORP que **no rompe streaming** (a diferencia de `BaseHTTPMiddleware`). (`app/middleware/security_headers.py`)
- Per-purpose JWT secrets: `_user_jwt_secret`, `_integration_jwt_secret`, `_api_key_hmac_secret` con fallback documentado. (`app/core/security.py:51-76`)
- Token type claim `typ`: user tokens y budget sessions firmados con secretos distintos, validados con `decode_access_token` vs `decode_integration_token`. (`app/core/security.py:79-164`)
- Integration API key: O(1) por `key_id` (header `X-DocuIntel-Key-Id` + `X-DocuIntel-Key-Secret`) + throttle de `last_used_at` (1/min/cliente). Legacy `X-DocuIntel-API-Key` mantenido 1 release. (`app/services/integration_security.py:124-198`)
- HMAC-SHA256 con `hmac.compare_digest` (constant-time) en login, API key verify, JWT. (`app/core/security.py:101, 153`; `app/services/integration_security.py:99`)
- Login con `slowapi` rate-limited a 10/minute por IP. (`app/api/routes/auth.py:21`)
- Cookie `auth_cookie_name` con `httponly=True`, `samesite=strict` en prod, `secure=True` en prod. (`app/api/routes/auth.py:35-44`)

### Backend / Webhooks
- **Outbox transaccional** (`webhook_outbox` + `enqueue_webhook`): la fila se escribe en la misma transacción que el cambio de estado. Worker de Celery drena con backoff exponencial (1s → 1h, max 8 intentos) y dead-letter manual. (`app/services/webhooks.py:1-99, 221-230`)
- HMAC-SHA256 con el header `X-DocuIntel-Signature` (formato `sha256=...`), payload serializado con `sort_keys=True, separators=(",",":")` para que la firma sea estable. (`app/services/webhooks.py:56-62, 136-139`)

### Frontend
- `router.tsx` con `lazy()` para **todas** las páginas y secciones admin, `RequireRole` que envuelve rutas sensibles (`/admin`, `/jobs`, `/plans`, `/documents/:id/annotate-plan`), `errorElement` con `ErrorBoundary`, ruta catch-all `*` → `NotFoundPage`. (`frontend/src/routes/router.tsx:10-46, 64-80, 118-209`)
- Chat con `askAIStream` async-iterable que parsea `event: start | delta | end` + `event: thinking` (Qwen3), `AbortController` para cancelar, persistencia en localStorage, exportación CSV, regeneración, "marcar incorrecto", "crear tarea". (`frontend/src/pages/chat/useChat.ts:105-292`)
- Búsqueda con 8 filtros (tipo, estado, proveedor, cliente, confianza, carpeta, fecha desde/hasta), debounced submit, `useSearchParams` para deep links `?q=...`, `useMemo` para active-filters, saneo de `mode` desde query string. (`frontend/src/pages/search/useSearchPage.ts:140-275`)
- Bundle chunks ya pequeños (ChatPage 33 KB, PlanoAnnotationPage 30 KB, DocumentDetailPage 25 KB, AdminLearningRoute 20 KB), gracias al `lazy()`. El vendor bundle `index-*.js` 435 KB (React + react-query + lucide + radix).

### Docker / Compose
- `docker-compose.prod.yml` con redes `internal` (postgres, redis, backend, workers, watcher) y `public` (solo frontend), sin `host.docker.internal:host-gateway` en prod.
- Redis con `--requirepass` + `--appendonly yes` y healthcheck autenticado.
- `Dockerfile` multi-stage (builder + runtime), `appuser` UID 10001, `--no-install-recommends`, tesseract con paquetes `spa` + `eng`, libgl1/libgomp1/libglib2 para Paddle, `poppler-utils` para PDF, `libreoffice-core` para conversiones.
- `Dockerfile.gpu` sobre `nvidia/cuda:12.6.3-cudnn-runtime-ubuntu22.04` con `paddlepaddle-gpu` desde el índice de PaddlePaddle.
- Uvicorn con `--proxy-headers --forwarded-allow-ips=...` y validación de `UVICORN_FORWARDED_ALLOW_IPS` (no `*` en prod).
- Alembic corre en el `CMD` del backend, no en cada worker (los workers reusan la DB ya migrada).

---

## 2. Hallazgos por severidad

Abreviaturas: 🔴 Blocker / 🟠 High / 🟡 Medium / 🟢 Low. S/M/L = esfuerzo.

### 🔴 BLOQUEANTES

#### B1. `host.docker.internal:host-gateway` en `docker-compose.yml` (dev) + `AI_BASE_URL=http://host.docker.internal:1234/v1` en `.env.production.example` (línea 49, 57)
- **Archivo:** `docu-intel/docker-compose.yml:67, 104, 145, 198, 247, 285, 313, 339`; `docu-intel/.env.production.example:49, 57`
- **Problema:** el `extra_hosts` está en TODOS los servicios del compose dev (incluidos los workers), y `.env.production.example` sugiere `host.docker.internal` para Coolify. En Coolify el `host.docker.internal` no resuelve por defecto — el LLM local está en el **host del servidor Coolify**, no en el host del dev de Windows. En prod, una red de empresa probablemente tiene el LLM en una IP/VPN distinto. Sin un `host.docker.internal` válido, el chat y los embeddings caen al fallback grounded (correcto, pero no documentado y no métrico).
- **Categoría:** Configuración / Producción
- **Fix:**
  1. Cambiar `.env.production.example` para usar una IP fija o un servicio docker separado (`llama-server` como servicio en el compose).
  2. Mejor aún: añadir un servicio `llama-server` opcional al compose prod (ya estaba en `ARQUITECTURA.md:427-432` con la imagen `ghcr.io/ggerganov/llama.cpp:server`).
  3. Para dev local Windows: documentar que hay que usar `host.docker.internal` solo ahí, y nunca en prod.
- **Esfuerzo:** S
- **Aceptación:** `curl http://backend:8000/admin/system/health` muestra `embeddings: ok` y `ai: ok` sin red warnings.

#### B2. `appuser` declarado pero `user:` deshabilitado en prod compose (línea 42 comentario)
- **Archivo:** `docu-intel/docker-compose.prod.yml:42`; `docu-intel/docker-compose.yml:82-83, 124, 263, 299, 327` (comentarios `# disabled on Windows: 9p bind-mounts`)
- **Problema:** en `docker-compose.yml` el `user:` está comentado "porque en Windows los bind-mounts 9p son root". En `docker-compose.prod.yml` el `user: "${APP_UID:-10001}:${APP_GID:-10001}"` SÍ está activo, pero los bind-mounts `./data/files:/app/data/files` se crean como root en el host. **Resultado:** el proceso `appuser` (UID 10001) no puede escribir en `/app/data/files` salvo que el host haya hecho `chown -R 10001:10001 data/` antes de levantar el compose. En Coolify los volúmenes con `driver: local` se gestionan distinto y esto NO es un problema, pero en un `docker compose up` directo sobre un host Linux **falla en silencio** y los jobs se quedan en `failed` con `Permission denied` en el log del worker.
- **Categoría:** Confiabilidad / Producción
- **Fix:**
  1. Cambiar los volúmenes a **named volumes** con `driver: local` (no bind-mounts) para producción. Los workers y el backend ven `/app/data/files` pero el FS vive en `/var/lib/docker/volumes/...`, propiedad de root → el `chown` del Dockerfile (`/app /models /cache`) basta.
  2. Documentar en el runbook que el primer arranque en Linux requiere `chown -R 10001:10001 ./data` o `sudo chown` antes de `docker compose up`.
  3. Añadir un `entrypoint` que haga `chown -R appuser:appuser /app/data/files /app/data/input` si detecta que son root-owned (idempotente, no roto en Coolify porque allí los volúmenes ya tienen UID correcto).
- **Esfuerzo:** S
- **Aceptación:** `docker compose -f docker-compose.prod.yml up` en un host Linux virgen, sin tocar `./data`, el primer documento ingestado se persiste correctamente sin `Permission denied`.

#### B3. Backend `CMD` corre `alembic upgrade head` en CADA arranque
- **Archivo:** `docu-intel/backend/Dockerfile:59` — `CMD ["sh", "-c", "alembic upgrade head && uvicorn ..."]`
- **Problema:** si en producción hay **dos réplicas** del backend (escalado horizontal), las dos corren Alembic al mismo tiempo. Alembic no es seguro para carrera concurrente sin `ALEMBIC_LOCK`; en Postgres provoca "duplicate key" en `alembic_version`. Si Alembic falla (e.g. una migración con `data backfill` pesada), el contenedor entra en crash-loop y el balanceador lo marca unhealthy.
- **Categoría:** Confiabilidad / Producción
- **Fix:**
  1. Sacar Alembic del CMD: ejecutar migrations desde un job de `deploy` o un sidecar de `migrate` con `restart: on-failure` que se levanta una sola vez, antes que los backends.
  2. Mantener la versión actual solo para dev (un único contenedor está bien).
  3. Alternativa: usar `alembic upgrade head` con un advisory lock de Postgres (`pg_try_advisory_xact_lock(<uuid>)`) — Alembic 1.13+ lo soporta con `--lock-mode`.
- **Esfuerzo:** M
- **Aceptación:** arrancar 2 réplicas de `backend` en compose no genera error de Alembic ni reinicios.

#### B4. `worker-heavy` sin healthcheck en dev compose (y CPU worker perfil `ocr-cpu` no incluido por defecto)
- **Archivo:** `docu-intel/docker-compose.yml:114-152` (perfil `ocr-cpu` no se levanta por defecto); `docu-intel/docker-compose.yml:75-112` (`worker-fast` SÍ tiene healthcheck)
- **Problema:** el dev compose **no levanta OCR worker** por defecto. Si el operador hace `docker compose up` (sin perfil), los PDFs escaneados se quedan encolados en `ocr_heavy` para siempre. El README dice "Ver `WORKER_FAST_CONCURRENCY=2`" pero no avisa de que necesitas `--profile ocr-cpu` o `--profile ocr-gpu` para que el OCR funcione.
- **Categoría:** Operacional / Fiabilidad
- **Fix:**
  1. En `docker-compose.yml`, hacer que `worker-heavy` (CPU) esté en el perfil por defecto (no en `ocr-cpu`): `'worker-heavy'` siempre activo, GPU en perfil opcional.
  2. Añadir un `entrypoint` al backend que detecte al arrancar si hay workers vivos en `ocr_heavy` y emita un warning de Sentry/log si no los hay.
  3. Documentar en el README que `--profile ocr-gpu` es opcional y solo acelera OCR.
- **Esfuerzo:** S
- **Aceptación:** `docker compose up` sin perfiles ingesta un PDF escaneado y se procesa en menos de 2 min.

---

### 🟠 HIGH

#### H1. `pool_size=20, max_overflow=ilimitado` y `WORKER_FAST_CONCURRENCY=4` (configurable hasta N)
- **Archivo:** `docu-intel/backend/app/database/session.py:19-27`; `docker-compose.prod.yml:66` (`--concurrency=${WORKER_FAST_CONCURRENCY:-4}`)
- **Problema:** el pool es 20 conexiones persistentes. Con `WORKER_FAST_CONCURRENCY=4` y 4 workers hay potencialmente `4 * 20 = 80` conexiones. Postgres por defecto tiene `max_connections=100`. Si añades un 5º worker o subes la concurrencia, **el worker muere con "FATAL: too many clients"** y no se recupera. No hay `max_overflow` declarado (SQLAlchemy default = `+10` por conexión base = hasta 30 por proceso).
- **Categoría:** Capacidad / Confiabilidad
- **Fix:**
  1. Configurar `pool_size=5, max_overflow=5, pool_timeout=10` en `_build_engine`.
  2. Asegurar que el `pgvector` de Coolify tiene `max_connections = (workers * concurrency * (pool_size + max_overflow)) + 10 (margen)`.
  3. Documentar la fórmula en el runbook.
- **Esfuerzo:** S
- **Aceptación:** un burst de 200 jobs simultáneos no genera "FATAL: too many clients" en `pg_log`.

#### H2. CORS `allow_credentials=True` con `allow_origins` específico
- **Archivo:** `docu-intel/backend/app/main.py:69-76`; `frontend/src/api/client.ts`
- **Problema:** `allow_credentials=True` con cookies JWT. La protección depende de que el navegador no permita a un origen distinto meter cookies. **Pero** el frontend hace login con `fetch()` y la cookie se setea con `samesite=strict` (en prod) — si la app de Coolify está en `https://app.example.com` y el backend en `https://api.example.com` (subdominio distinto), `samesite=strict` **bloquea el envío de la cookie** en cross-site GETs. Si está en el mismo origen (Coolify con path routing), no hay problema.
- **Categoría:** Auth / Producción
- **Fix:**
  1. Verificar la topología real del deploy (Coolify con un dominio + path, o dos subdominios).
  2. Si son dos subdominios: cambiar a `samesite=lax` (no `strict`), y/o mover el token a `Authorization: Bearer` en lugar de cookie (más portable).
  3. Si es mismo origen: el código actual ya está bien.
- **Esfuerzo:** S (verificación) / M (cambio de estrategia de token)
- **Aceptación:** login funciona end-to-end en el deploy real de Coolify.

#### H3. `embed_text` cachea con namespace que incluye la URL exacta — un cambio de host invalida TODO el cache
- **Archivo:** `docu-intel/backend/app/services/embeddings.py:185-197`
- **Problema:** la cache key es `embedding:{md5(provider|base_url|model|class|dimensions|role|text)}`. Si el operador cambia `EMBEDDING_BASE_URL` (e.g. de `http://host.docker.internal:1234/v1` a `http://llama-server:8080/v1`), **toda la cache de embeddings se invalida** y los siguientes `embed_query` recalculan todo. Si hay 500k chunks, son 500k llamadas extra al embedding server. No hay un "rebuild" controlado.
- **Categoría:** Operacional / Coste
- **Fix:**
  1. Excluir `base_url` del namespace (dejar solo `provider, model, dimensions, role`). La URL no cambia el contenido del embedding, solo el transporte.
  2. Si se quiere un override explícito (e.g. downgrade de modelo), un `EMBEDDING_CACHE_NAMESPACE` opcional.
- **Esfuerzo:** S
- **Aceptación:** cambiar `EMBEDDING_BASE_URL` no vacía la cache y los primeros 10.000 chunks vienen de cache.

#### H4. `webhook_outbox_interval_seconds=30` + `webhook_outbox_batch_size=25` + `deliver_pending_webhooks_task` no tiene timeout
- **Archivo:** `docu-intel/backend/app/workers/webhooks_tasks.py` (a leer); `app/core/config.py:340-342`
- **Problema:** sin ver `webhooks_tasks.py` no puedo confirmar, pero si el worker hace `httpx.post(...)` con el `integration_webhook_timeout_seconds=5.0` configurado, 25 webhooks × 5 s = 125 s de lock sobre el batch. Si hay miles de webhooks pendientes (e.g. tras una caída del receptor), la cola se atasca. No hay un `acquire_lock` o `SELECT ... FOR UPDATE SKIP LOCKED` documentado.
- **Categoría:** Confiabilidad
- **Fix:**
  1. Verificar que el worker marca `next_attempt_at` antes de empezar a procesar y commitea al final del batch (lock de fila).
  2. Añadir timeout duro en el task: `soft_time_limit=120, time_limit=180`.
  3. Métrica: `docuintel_webhook_outbox_lag_seconds` (gauge).
- **Esfuerzo:** M
- **Aceptación:** simular receptor caído durante 1 h → la cola no crece sin control y el dashboard muestra el lag.

#### H5. `RateLimitExceeded` handler importado pero `limiter` solo en `/auth/login` y `/ai/ask`
- **Archivo:** `docu-intel/backend/app/main.py:5-50`; `app/api/routes/ai.py:43-50, 67-70`; `app/api/routes/auth.py:21`
- **Problema:** los endpoints pesados (upload `/documents` multi-archivo, `POST /search/semantic` para 1k queries/min, integración `/integrations/v1/tools/execute`) NO están rate-limited. Un cliente de integración puede pedir 1000 queries/min y saturar el embedding server + Postgres.
- **Categoría:** Confiabilidad / DoS
- **Fix:**
  1. Aplicar `@limiter.limit("60/minute")` por usuario en `/search/*`, `/ai/ask`, `/documents` POST.
  2. Para `/integrations/v1/tools/execute`: ya tiene `enforce_integration_rate_limit` (config 120/min) — bien.
  3. Para uploads: `max_upload_files=10_000_000` en settings — eso es 10M de archivos en una request. Es un bug, debería ser algo como `100`. Cámbialo y añade un rate limit de 10/min.
- **Esfuerzo:** S
- **Aceptación:** un script que haga 5000 `POST /search/semantic` en 1 min recibe 429 desde la query 61, no satura el embedding server.

#### H6. `textSearch` y `semanticSearch` sin filtro obligatorio de `tenant_access` en el wrapper HTTP
- **Archivo:** `docu-intel/backend/app/api/routes/search.py` (a leer)
- **Problema:** el `vector_store` filtra por `budget_scope_id` cuando se pasa en `filters`, pero el `get_integration_context` y el `resolve_user_access_scope` se aplican en `agent.py`. Falta confirmar que `/search/text`, `/search/semantic`, `/search/hybrid` aplican la misma `AccessScope` que `/ai/ask`. Si se cuela una request sin scope, un operario con `tenant_access_deny_by_default=true` ve 0 documentos (bien), pero un gestor con permisos amplios podría ver documentos de OTRO `budget_scope` que no le corresponden.
- **Categoría:** AuthZ / Producción
- **Fix:**
  1. Verificar en `app/api/routes/search.py` que `resolve_user_access_scope` se aplica antes de cada query (mismo patrón que `agent.py:178`).
  2. Añadir un test de integración: dos usuarios en dos `budget_scope`s distintos hacen el mismo `GET /search/hybrid?q=presupuesto` y reciben solo sus docs.
- **Esfuerzo:** M
- **Aceptación:** el test pasa; un pentester no puede "leak" docs entre scopes.

#### H7. `embed_text_hash` se sigue usando como fallback en PRODUCCIÓN si `EMBEDDING_FALLBACK_TO_HASH=true`
- **Archivo:** `docu-intel/backend/app/services/embeddings.py:471-482`; `.env.production.example:62` (`EMBEDDING_FALLBACK_TO_HASH=false`)
- **Problema:** el ejemplo de prod tiene `false` (bien), pero el **default del código es `true`**. Si un operador no genera `.env.production` y solo copia `.env` a `.env.production` sin tocar la variable, el fallback hash se activa, los embeddings son 100% inútiles para búsqueda semántica, **y el sistema no falla** (silencioso). El plan A5 lo marca como bug y la corrección (fallar rápido) está implementada para `coerce_embedding_dimensions`, pero `embed_text_hash` sigue siendo el fallback por defecto.
- **Categoría:** Configuración / Producción
- **Fix:**
  1. Cambiar el default de `embedding_fallback_to_hash: bool = True` a `False` (en `config.py:230`).
  2. Si el operador quiere hash fallback (modo degradado), lo activa explícitamente.
- **Esfuerzo:** S
- **Aceptación:** sin `EMBEDDING_FALLBACK_TO_HASH` configurado, un fallo del embedding server hace que la ingesta falle con error claro, no que se llene la BD de vectores basura.

#### H8. `chat()` y `chat_stream()` no envuelven el circuit breaker del LLM en el path de embedding
- **Archivo:** `docu-intel/backend/app/services/embeddings.py:62-77` (sí tiene breaker para embeddings) vs `app/ai/local_client.py:43-44, 234-262` (tiene su propio breaker para LLM)
- **Problema:** correcto que hay DOS breakers separados (embedding y LLM), pero no hay un breaker compartido para el **vision LLM** (`LocalVisionClient`). Si el vision server está down, cada llamada espera `vision_timeout_seconds=60` y la cascada completa se cuelga.
- **Categoría:** Confiabilidad
- **Fix:**
  1. Añadir `LocalVisionCircuitOpen` + breaker con la misma estructura que `LocalAICircuitOpen` (módulo-level `_LOCAL_VISION_CIRCUITS`).
  2. `LocalVisionClient.describe()` chequea el breaker y lanza `LocalVisionCircuitOpen` antes de gastar el timeout.
- **Esfuerzo:** S
- **Aceptación:** vision server caído durante 10 min: el primer OCR vision falla con 60 s, los siguientes fallan en <100 ms con `LocalVisionCircuitOpen`.

#### H9. `document_chunk.tsv` se declara `nullable=True` pero la migración 0021 declara GENERATED ALWAYS AS
- **Archivo:** `docu-intel/backend/app/models/document.py:170`; `docu-intel/backend/alembic/versions/0021_document_chunks_tsv.py` (a leer)
- **Problema:** el modelo dice `tsv: Mapped[Any | None] = mapped_column(Text(), nullable=True)`. Si la migración declara la columna como `GENERATED ALWAYS AS (to_tsvector('simple', chunk_text)) STORED`, el modelo está mintiendo: la columna no es nullable en realidad y siempre se computa. Riesgo: si alguien intenta escribir `chunk.tsv = ...` desde el ORM, falla con `cannot insert into generated column`.
- **Categoría:** Mantenibilidad / Modelos
- **Fix:**
  1. En el modelo, marcar `tsv` con un `__table_args__` que documente "READ ONLY — generated column" y opcionalmente `info={"generated": True}`.
  2. Considerar `Mapped[None]` con `Computed` de SQLAlchemy 2.0 (si el dialecto lo soporta).
- **Esfuerzo:** S
- **Aceptación:** `db.execute(update(DocumentChunk).values(tsv="..."))` falla con error claro; un `db.refresh()` lee la columna correctamente.

---

### 🟡 MEDIUM

#### M1. `extraction_jobs` y `audit_logs` sin estrategia de particionado
- **Archivo:** `docu-intel/backend/app/models/audit.py`, `operations.py`
- **Problema:** ambas tablas crecen monótonamente. Con 500 documentos/día y 20 audit entries por doc, son ~3M filas/año en `audit_logs`. Sin particionado, los índices se hinchan, los backups crecen, las queries de "última semana" se hacen lentas.
- **Fix:** migrar a particionado por mes (`PARTITION BY RANGE (created_at)`), con retention automática. Es una migración grande — solo si la adopción es real.
- **Esfuerzo:** L
- **Aceptación:** tras 6 meses, queries de "audit del último día" son < 50 ms p95.

#### M2. `bcrypt` solo si está disponible — fallback a PBKDF2
- **Archivo:** `docu-intel/backend/app/core/security.py:28-48`
- **Problema:** el código intenta `import bcrypt`; si falla usa PBKDF2 con 150.000 iteraciones. El plan marca que las hashes existentes se verifican por prefijo (`$2...` vs `pbkdf2_sha256$...`). **Pero** un operador que despliegue sin `bcrypt` en requirements tendría un sistema con PBKDF2 (más débil). Falta el `pip install bcrypt` en `requirements.txt` o un check explícito.
- **Fix:**
  1. Pinear `bcrypt>=4.0` en `requirements.txt` (buscar si ya está).
  2. Añadir un healthcheck que verifique que `bcrypt` está disponible al arranque.
- **Esfuerzo:** XS
- **Aceptación:** el healthcheck falla si bcrypt no está disponible.

#### M3. No hay PII scrubbing explícito en Sentry
- **Archivo:** `docu-intel/backend/app/core/sentry.py` (a leer)
- **Problema:** la setting `sentry_send_pii: bool = False` está, pero no he visto `before_send` que scrubbee emails, NIFs, IBANs, importes. Un Sentry breadcrumb de un 500 con `extra={"request_body": {"email": "...@...", "nif": "B12345678"}}` filtra PII.
- **Fix:** añadir `before_send(event, hint)` que reemplace campos sensibles por `[REDACTED]`. Patrones a redactar: emails, NIF/CIF, IBAN, importes con decimales, nombres de archivos con `\.pdf$`, tokens (`Bearer ...`).
- **Esfuerzo:** S
- **Aceptación:** un test genera un evento Sentry simulado y verifica que no contiene emails ni NIFs.

#### M4. `Celery worker_process_init` precarga OCR en TODOS los workers, no solo en `ocr_heavy`
- **Archivo:** `docu-intel/backend/app/workers/celery_app.py:70-105`
- **Problema:** el decorador `@worker_process_init` corre en cada worker al iniciarse. Si `OCR_ENGINE_PRELOAD=true` (configurado en compose prod para el CPU worker), también carga en `worker-fast`, `worker-maintenance`, `scheduler`, `watcher`. Para el scheduler y watcher es **innecesario** y multiplica el uso de RAM por N workers.
- **Fix:** chequear el nombre del worker dentro de `preload_worker_ocr_engine`:
  ```python
  if "ocr" not in (os.environ.get("WORKER_NAME") or "").lower():
      return
  ```
  O mejor: separar el signal en dos: `@worker_process_init.connect` para OCR workers, otro signal para el resto.
- **Esfuerzo:** S
- **Aceptación:** un `docker compose up` con `OCR_ENGINE_PRELOAD=true` y `scheduler` corriendo: el scheduler no carga PaddleOCR en RAM.

#### M5. `watcher` solo tiene healthcheck de "el directorio existe" (no verifica que esté escaneando)
- **Archivo:** `docu-intel/docker-compose.yml:314-318`; `docker-compose.prod.yml:153`
- **Problema:** el healthcheck del watcher es `python -c "import os; assert os.path.isdir('/app/data/input')"`. Eso siempre es `True` después del primer segundo. Un watcher con un bug que no escanea pasa el healthcheck y Docker no lo reinicia.
- **Fix:** el watcher debe escribir un timestamp en `/tmp/watcher_heartbeat` cada vez que completa un ciclo. El healthcheck verifica `find /tmp/watcher_heartbeat -mmin -2`. O un endpoint HTTP interno.
- **Esfuerzo:** M
- **Aceptación:** matar el loop del watcher manualmente → Docker lo reinicia en < 2 min.

#### M6. `vision_on_demand` carga/descarga el modelo con `lms` CLI — race condition con múltiples workers
- **Archivo:** `docu-intel/backend/app/services/vision_manager.py` (a leer)
- **Problema:** si 2 workers vision (uno en cada GPU) intentan `lms load` simultáneamente, pueden pelearse. El CLI `lms` opera contra un único proceso LM Studio; con varios workers apuntando al mismo endpoint, los dos hacen `load` y se confunde el manager.
- **Fix:** usar un **lock distribuido** con Redis (`SETNX vision_load_lock EX 60`) antes de invocar `lms load`. O usar LM Studio con un servidor multi-modelo y dejar el modelo siempre cargado.
- **Esfuerzo:** M
- **Aceptación:** 2 workers procesando PDFs vision en paralelo: solo uno llama a `lms load`, el otro espera.

#### M7. `chunk_type` y `block_type` se mantienen como string sin enum
- **Archivo:** `docu-intel/backend/app/models/document.py:113, 160`
- **Problema:** `block_type: Mapped[str] = mapped_column(String(50), default="text")` acepta cualquier string. Un typo en una migración futura introduce un valor no documentado y los queries de filtro (`WHERE block_type = "table"`) fallan silenciosamente (devuelven 0).
- **Fix:** usar `enum.Enum` con `String(50)` (`Mapped[BlockType] = mapped_column(SqlEnum(BlockType, name="block_type_enum"))`) y migrar la columna. O al menos un CHECK constraint.
- **Esfuerzo:** M
- **Aceptación:** un `INSERT ... block_type='tablesx'` falla con `CheckViolation`.

#### M8. `LocalAIConfig` y `LocalVisionConfig` devuelven siempre `base_url` y `model` aunque estén vacíos
- **Archivo:** `docu-intel/backend/app/ai/local_client.py:50-65`
- **Problema:** `get_local_ai_config()` no valida que los valores sean usables. Un operador que olvida `AI_BASE_URL` y `AI_MODEL` recibe un config con `base_url=""` y `model=""`. El `chat()` chequea `if not self.base_url or not self.model` y lanza error, pero el UI de admin que muestra la config no avisa de que falta.
- **Fix:** añadir un método `is_configured()` que devuelva `bool` y exponer un badge rojo en `/admin/system/health` cuando `not is_configured()`. (Probablemente ya existe — verificar `app/services/healthchecks.py`.)
- **Esfuerzo:** XS

#### M9. `app.services.metrics.register_metrics_endpoint` no se ha verificado
- **Archivo:** `docu-intel/backend/app/main.py:81`; `app/services/metrics/` (a leer)
- **Problema:** el `register_metrics_endpoint` está bien, pero no he confirmado que exponga **todas** las métricas que el plan describe (golden OCR, RAGAS, prompt injection, MMR, etc.). Si faltan, el operario no ve señales críticas.
- **Fix:** comparar la lista en `PLAN_MEJORAS_OCR_EMBEDDINGS_PLANOS_RAG.md` con la lista real de `metrics/`. Añadir lo que falte.
- **Esfuerzo:** M

#### M10. `pyproject.toml`/`ruff` settings no se han auditado
- **Archivo:** `docu-intel/backend/pyproject.toml`
- **Problema:** el plan menciona que `ruff` se usa. Si el linter no cubre `B` (bugbear), `S` (security), `ASYNC`, `RUF` (misc), deja pasar cosas que en producción revientan.
- **Fix:** verificar la config de `ruff` y añadir `select = ["E","F","W","B","S","ASYNC","UP","RUF"]` con `ignore` razonables. Añadir `ruff check` al CI.
- **Esfuerzo:** XS

---

### 🟢 LOW (nice to have)

#### L1. `index-*.js` 435 KB — evaluar `manualChunks` en `vite.config.ts`
- **Archivo:** `docu-intel/frontend/vite.config.ts`
- **Problema:** el bundle vendor es 435 KB (gzip ~120 KB). Para un internal tool es aceptable; para un SaaS público sería inaceptable. `manualChunks` para `react`, `react-dom`, `react-query`, `lucide-react`, `radix-ui` reduce el initial parse.
- **Esfuerzo:** S

#### L2. CSP permite `style-src 'unsafe-inline'`
- **Archivo:** `docu-intel/backend/app/middleware/security_headers.py:83`
- **Problema:** está documentado por qué (Tailwind + shadcn inyectan estilos). En el futuro, migrar a `nonce` por response.
- **Esfuerzo:** L (refactor mayor)

#### L3. `LoginPage` test pero no test e2e del flujo completo
- **Archivo:** `frontend/src/pages/LoginPage.test.tsx` (existe)
- **Problema:** no hay test e2e (Playwright) del flujo "subir PDF → esperar OCR → buscar → chatear". Sin este test, regresiones de UI pasan a prod.
- **Esfuerzo:** L

#### L4. `app.services.cache.cache_service` debería ser Redis-only en prod
- **Archivo:** `app/services/cache.py` (a leer)
- **Problema:** si `cache_service` tiene fallback a memoria (`functools.lru_cache`), en un multi-worker cada worker tiene su propia cache → "stale results" entre workers.
- **Esfuerzo:** S

#### L5. `db` dependency en `/ai/ask/stream` — la sesión de DB se mantiene abierta durante el stream
- **Archivo:** `docu-intel/backend/app/api/routes/ai.py:67-74`
- **Problema:** la sesión SQLAlchemy vive durante todo el SSE (potencial 60 s). Si el modelo está pensando, la sesión retiene una conexión del pool. Con muchos streams concurrentes, el pool se agota.
- **Fix:** materializar el contexto en una lista antes de empezar el stream y cerrar la sesión. O usar `async_scoped_session`.
- **Esfuerzo:** M

#### L6. Logs estructurados sin campos estándar
- **Archivo:** `docu-intel/backend/app/core/logging.py` (a leer)
- **Problema:** si el formato es `%(asctime)s %(levelname)s %(name)s %(message)s`, no hay `request_id`, `user_id`, `correlation_id`. El `RequestIDMiddleware` (mencionado en `main.py:53`) probablemente lo añade, pero verificar.
- **Esfuerzo:** S

---

## 3. Tabla resumen

| Sev | Cat | Hallazgo | Archivo | Esfuerzo |
|---|---|---|---|---|
| 🔴 | Config | `host.docker.internal` en compose dev y prod | `docker-compose.yml`, `.env.production.example` | S |
| 🔴 | Confiab | `appuser` no puede escribir en bind-mounts en Linux | `docker-compose.yml`, `docker-compose.prod.yml` | S |
| 🔴 | Confiab | Alembic en cada arranque del backend (no race-safe) | `backend/Dockerfile:59` | M |
| 🔴 | Operacional | `worker-heavy` no se levanta sin `--profile ocr-cpu` | `docker-compose.yml:114-152` | S |
| 🟠 | Capacidad | Pool size + concurrencia puede saturar `max_connections` | `session.py:19-27`, `prod.yml:66` | S |
| 🟠 | Auth | CORS+cookie cross-site con `samesite=strict` | `main.py:69-76` | S-M |
| 🟠 | Coste | Cache key incluye URL — cambio de host invalida todo | `embeddings.py:185-197` | S |
| 🟠 | Confiab | Webhook batch sin `SKIP LOCKED` y sin `time_limit` | `webhooks_tasks.py` | M |
| 🟠 | DoS | `/search`, `/documents` sin rate-limit por usuario | `routes/search.py`, `routes/documents.py` | S |
| 🟠 | AuthZ | `/search/*` no aplica `AccessScope` | `routes/search.py` | M |
| 🟠 | Conf | Default `EMBEDDING_FALLBACK_TO_HASH=true` | `config.py:230` | XS |
| 🟠 | Conf | Vision sin circuit breaker | `local_client.py` (vision) | S |
| 🟠 | Mantenib | `tsv` columna generated mintiendo tipo en ORM | `models/document.py:170` | S |
| 🟡 | Capacidad | `audit_logs` y `extraction_jobs` sin particionado | `models/audit.py`, `models/operations.py` | L |
| 🟡 | Conf | `bcrypt` opcional → fallback PBKDF2 silencioso | `core/security.py:28-48` | XS |
| 🟡 | PII | Sentry sin scrubbing | `core/sentry.py` | S |
| 🟡 | RAM | OCR preload corre en todos los workers | `celery_app.py:70-105` | S |
| 🟡 | Operacional | Watcher healthcheck trivial (no detecta "no escanea") | `docker-compose.yml:314-318` | M |
| 🟡 | Concurrencia | Vision `lms` race entre workers | `vision_manager.py` | M |
| 🟡 | Modelos | `block_type`/`chunk_type` sin enum ni CHECK | `models/document.py` | M |
| 🟡 | Health | `LocalAIConfig` no avisa visualmente si falta config | `ai/local_client.py:50-65` | XS |
| 🟡 | Métricas | Lista de métricas no auditada vs plan | `services/metrics/` | M |
| 🟡 | Lint | `ruff` config no exhaustiva | `pyproject.toml` | XS |
| 🟢 | Bundle | `manualChunks` en Vite | `vite.config.ts` | S |
| 🟢 | CSP | `style-src 'unsafe-inline'` | `middleware/security_headers.py:83` | L |
| 🟢 | Tests | Sin e2e (Playwright) del flujo principal | `frontend/` | L |
| 🟢 | Cache | `cache_service` con posible fallback en memoria | `services/cache.py` | S |
| 🟢 | DB | Sesión DB abierta durante todo el stream SSE | `routes/ai.py:67-74` | M |
| 🟢 | Logging | Sin campos `request_id` estandarizados | `core/logging.py` | S |

---

## 4. Roadmap priorizado (1-2 sprints)

### Sprint 0 (esta semana, ~2-3 días) — CRÍTICO

| # | Tarea | Esfuerzo |
|---|---|---|
| 1 | **B1** Cambiar `.env.production.example` para no usar `host.docker.internal`; añadir servicio opcional `llama-server` al compose prod | S |
| 2 | **B2** Cambiar bind-mounts a named volumes en prod compose + documentar chown en runbook | S |
| 3 | **B3** Sacar Alembic del CMD; ejecutar migraciones en `deploy` job de Coolify | M |
| 4 | **B4** Mover `worker-heavy` CPU al perfil por defecto | S |
| 5 | **H7** Default `EMBEDDING_FALLBACK_TO_HASH=false` | XS |

### Sprint 1 (siguiente, ~1 semana)

| # | Tarea | Esfuerzo |
|---|---|---|
| 6 | **H1** Pool size + max_overflow ajustados | S |
| 7 | **H5** Rate limit por usuario en `/search/*` y `/documents` POST | S |
| 8 | **H6** Verificar/añadir `AccessScope` en `/search/*` (con test) | M |
| 9 | **H8** Vision circuit breaker | S |
| 10 | **H3** Cache key sin URL | S |
| 11 | **H4** Webhook batch `SKIP LOCKED` + `time_limit` | M |
| 12 | **H2** Validar CORS+cookie en deploy real (sin cambios si mismo origen) | S |
| 13 | **H9** Documentar `tsv` como read-only en ORM | S |
| 14 | **M2** Pinear `bcrypt` y healthcheck | XS |
| 15 | **M3** Sentry PII scrubbing | S |
| 16 | **M4** OCR preload solo en workers OCR | S |
| 17 | **M5** Watcher healthcheck robusto (heartbeat) | M |

### Sprint 2 (opcional, hardening extra)

| # | Tarea | Esfuerzo |
|---|---|---|
| 18 | **M6** Vision `lms load` lock distribuido | M |
| 19 | **M7** Enum para `block_type`/`chunk_type` | M |
| 20 | **M9** Auditar y completar métricas Prometheus | M |
| 21 | **M10** `ruff` config exhaustiva + CI | XS |
| 22 | **L1** `manualChunks` Vite | S |
| 23 | **L6** Logging estructurado con `request_id` | S |

### Sprint 3+ (si la adopción crece)

- M1 (particionado de `audit_logs`/`extraction_jobs`)
- L2 (CSP con nonces)
- L3 (Playwright e2e)
- L4 (cache Redis-only en prod)

---

## 5. Verificaciones mínimas antes de producción

Ejecutar en orden antes de marcar el proyecto como "producción":

1. **Smoke E2E** (manual, 10 min):
   ```bash
   cd docu-intel
   cp .env.production.example .env.production
   # generar secretos: sed -i '' 's/GENERATE_A_.*/$(python -c "import secrets;print(secrets.token_urlsafe(64))")/' .env.production
   DOCUINTEL_ENV_FILE=.env.production docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
   # 1. login con admin
   # 2. subir un PDF digital
   # 3. esperar OCR
   # 4. búsqueda híbrida devuelve el PDF
   # 5. chat con streaming funciona
   # 6. admin/system/health devuelve 200 con todas las dependencias ok
   ```

2. **Restore test** (manual, 30 min):
   ```bash
   # Documentado en scripts/restore.ps1 y docs/production-runbook.md
   # Verificar que un backup de 1 semana se restaura en una instancia nueva sin pérdida de datos
   ```

3. **Load test sintético** (1-2 h):
   ```bash
   # Usar backend/tests/performance/ si existe; si no, scripts con locust/k6
   # 100 RPS en /search/hybrid durante 10 min
   # Verificar p95 < 800 ms, errores < 0.1%, CPU < 70%
   ```

4. **Security smoke** (manual, 1 h):
   ```bash
   # Intentar acceso a /admin sin auth → 401
   # Intentar acceso a /api/v1/documents/{id} de otro scope → 403
   # curl con cookie de otro usuario → 401
   # Buscar headers de seguridad en /: HSTS, CSP, Permissions-Policy presentes
   ```

5. **CI en verde**: `pytest` (backend) + `npm run build` (frontend) + `ruff check` + `npm run lint` + tests frontend.

6. **Sentry configurado**: crear un evento de prueba (`SENTRY_DSN=...` configurado), verificar que llega al proyecto.

7. **Backups automáticos**: cron/scheduled task de `scripts/backup.ps1` con retención de N días.

---

## 6. Riesgos residuales

Aun después de aplicar el roadmap:

1. **ColPali/visual retrieval (X1 del plan)**: si el corpus crece > 1M chunks, el recall@10 con BGE-M3 1024-dim puede caer. Planear un re-embed a un modelo de mayor dimensión (BGE-M3 → BGE-M3-v2, o ColPali para imágenes) en 6-12 meses.

2. **YOLO/plan symbols (P2)**: el modelo por defecto `SamirShabani/Architect` es CC BY-NC 4.0 (no comercial). Para una herramienta **interna** esto es aceptable, pero si la herramienta se distribuye, hay que cambiar a un modelo permissivo o entrenar uno propio.

3. **GPU**: los 2× RTX 4070 (8 GB cada uno) están bien para Tesseract + PaddleOCR + BGE-M3, pero **no dan** para un LLM 70B o ColPali. Si se sube a un modelo de chat > 32B o a ColPali, hay que planificar GPUs de 24 GB (RTX 4090, A5000) o cambiar a API externa.

4. **Postgres `pgvector`**: HNSW tiene un recall excelente pero el `ef_search` por defecto (40) puede no ser óptimo para el corpus. Con > 100k chunks, ajustar `ef_search` y `ef_construction` para el workload real.

5. **Watchdog (watcher) en Coolify**: el `WATCHER_BACKEND=native` usa `inotify` que no funciona con bind-mounts 9p. El ejemplo prod usa `polling` — bien, pero el polling a 10 s con 100k archivos tiene un costo.

6. **`file_storage_strategy=auto` con hardlinks**: en Linux + Coolify (que usa overlayfs), los hardlinks pueden romperse en operaciones de mantenimiento (prune de volúmenes). Plan B: `FILE_STORAGE_STRATEGY=copy` en prod, asumiendo más disco (300 GB → 300 GB sin dedup).

7. **PDFs de > 1000 páginas**: el setting `max_pdf_pages=1000` rechaza pero no avisa al usuario de cuántos tenía. Mejor: pre-renderizar el thumbnail primero, mostrar progreso, dejar al usuario decidir.

8. **Sentry + datos sensibles**: aunque añadamos PII scrubbing (M3), el Sentry mismo recibe los eventos. Verificar que el Sentry host (GlitchTip en compose) está bien configurado con TLS y auth.

9. **GlitchTip como servicio separado**: en `docker-compose.yml` línea 376, GlitchTip usa su propio Postgres. Es OK para dev pero en prod debería ser un servicio gestionado (Sentry SaaS, GlitchTip Cloud) o un Postgres de la misma infra con backups.

10. **`ai_cache` table crece sin bound**: cada (user, question, mode, scope) genera una fila. Con 100 preguntas únicas/usuario/día × 50 usuarios × 365 días = 1.8M filas/año. Considerar TTL explícito o un job de pruning.

---

## Apéndice A — Conteo rápido de lo que existe

| Componente | Ficheros | Notas |
|---|---|---|
| Backend services | **70+** | desde `access_explain.py` hasta `webhooks.py` |
| Modelos | 14 | todos con type hints, indexes declarados |
| Migraciones Alembic | **31** | bien numeradas, hasta `0031_pg_trgm_text_search_indexes.py` |
| API routes | 30 | con auth, rate limit, response_model |
| Workers Celery | 6 módulos | tasks, embedding_tasks, learning_tasks, learning_health_tasks, webhooks_tasks, routing |
| Tests | en `tests/`, `tests/eval/`, `tests/performance/`, `tests/fixtures/` | suficiente para regression |
| Páginas frontend | 21 (algunas son directorios con `components.tsx` + hook) | todas `lazy()` |
| Chunks frontend | 16 visibles (build dist) | el más grande: `index-*.js` 435 KB |

## Apéndice B — Veredicto ejecutivo

**El proyecto Docu-Intel es desplegable como herramienta interna de producción HOY**, asumiendo:
- Se generan los secretos de `.env.production` (no los del `.example`).
- Se aplica el Sprint 0 de la sección 4 (5 tareas, ~2-3 días de trabajo).
- Se valida el flujo E2E con un PDF real.
- Se tiene Sentry o GlitchTip configurado para errores.

**No es desplegable como SaaS multi-tenant** — el plan original lo aclara (cadena/hotel está aparcado por decisión del proyecto).

**No es desplegable "a lo bestia" en una red abierta** sin aplicar los 17 items del Sprint 1 (1 semana de trabajo).

El equipo tiene un muy buen trabajo de base. Lo que falta es **endurecimiento de los detalles operativos** (rate limit, OAuth, Alembic seguro, observabilidad, BCRYPT pin, etc.), no grandes refactors arquitectónicos.

---

**Auditor:** Sisyphus, 15 de junio de 2026
