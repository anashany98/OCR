# Análisis Integral de Optimización — Docu-Intel (Perspectiva 2)

## Resumen ejecutivo

4 análisis cruzados (arquitectura, seguridad, fiabilidad, UX) revelan **38 hallazgos** clasificados por severidad. Los 3 más urgentes son de seguridad (fuga de datos cross-tenant) y fiabilidad (jobs atascados, commits fuera de transacción).

---

## 🔴 CRÍTICO — Requiere acción inmediata

### SEC-1: AI aggregate tools bypasean tenant scope
- **Archivo:** `app/ai/context.py:285-289`
- **Problema:** `aggregate_business` consulta TODOS los budgets/orders sin aplicar `AccessScope` del usuario. Un usuario sin `can_view_prices` puede preguntar "suma de facturas" y recibir montos cross-tenant.
- **Fix:** Añadir `access_scope` al llamada `aggregate_business` en `collect_context`.

### SEC-2: Precios expuestos en resolved_document JSON
- **Archivo:** `app/api/routes/ai.py` (SSE end event) + `app/ai/agent.py`
- **Problema:** El payload `resolved_document` enviado por SSE y almacenado en `AIAnswer` contiene `total_amount`, `unit_price`, `total_price` sin redactar.
- **Fix:** Aplicar `redact_business_payload_for_scope()` al `resolved_json` antes de serializar.

### SEC-3: REST business endpoints ignoran can_view_prices
- **Archivos:** `app/api/routes/budgets.py`, `invoices.py`, `orders.py`
- **Problema:** Los endpoints REST devuelven importes sin verificar `can_view_prices` del usuario.
- **Fix:** Añadir redacción condicional en cada endpoint de negocio.

---

## 🟠 ALTO — Impacto significativo

### REL-1: Jobs atascados en "processing" permanentemente
- **Archivo:** `app/workers/document_processing_core.py`
- **Problema:** Si un worker muere entre el ack de Celery y el `db.commit()`, el job queda en "processing" para siempre. No hay sweeper periódico ni endpoint admin para resetear.
- **Fix:** Añadir Celery beat task cada 5min que resetee jobs `processing` con `started_at > now - 30min`. Añadir endpoint admin `POST /admin/jobs/{id}/reset`.

### REL-2: Hyper-Extract commit fuera de transacción principal
- **Archivo:** `app/workers/document_processing_core.py:659-701`
- **Problema:** `_maybe_run_hyperextract` hace `db.commit()` propio. Si el commit principal falla después, la fila de hyperextract queda huérfana.
- **Fix:** Mover la creación de la fila hyperextract DENTRO de la transacción principal, o deferirla hasta después del commit exitoso.

### REL-3: Archivos temporales de preprocessing nunca se borran
- **Archivo:** `app/ocr/preprocess.py:74-82`
- **Problema:** `NamedTemporaryFile(delete=False)` crea archivos que nunca se eliminan. Miles de páginas = fuga de disco lenta.
- **Fix:** Añadir `try/finally` con `Path(ocr_path).unlink(missing_ok=True)` después de cada `extract()` en `tesseract.py` y `paddle.py`.

### REL-4: Monitoreo con fallos invisibles
- **Archivos:** Múltiples
- **Problemas:** Jobs atascados, notificaciones fallidas, backups antiguos, cobertura de embeddings — todo silencioso.
- **Fix:** Añadir métricas Prometheus: `stale_jobs_total`, `notification_failure_total`, `backup_age_seconds`, `embedding_coverage_ratio`.

### ARCH-1: Vector(768) vs embedding_dimensions=1024
- **Archivo:** `app/models/document.py:209` vs `app/core/config.py:234`
- **Problema:** El modelo ORM declara `Vector(768)` pero el runtime usa 1024. Mismatch potencial.
- **Fix:** Verificar qué valor tiene la columna real en Postgres. Actualizar el ORM para que coincida.

### ARCH-2: Config monolítica (~170 settings)
- **Archivo:** `app/core/config.py` (626 líneas)
- **Problema:** Un solo `Settings` con todo. Redundancias: `embedding_base_url` / `ai_base_url`, 3 API keys separadas.
- **Fix:** Dividir en `OCRSettings`, `AISettings`, `EmbeddingSettings`, `VisionSettings`. Unificar API keys.

### UX-1: window.confirm en admin (8 usos)
- **Archivos:** `AdminOperationalPage.tsx`, `AdminIntegrationsPage.tsx`, `AdminQualityPage.tsx`, `AdminLearningPage.tsx`, `DocumentDetailPage.tsx`
- **Problema:** Bloquea JS thread, no es temable, inaccesible.
- **Fix:** Reemplazar por `useConfirm()` hook (ya existe).

### UX-2: Skeleton screens genéricos
- **Archivo:** `LoadingState.tsx` (9 líneas)
- **Problema:** Todas las páginas muestran el mismo placeholder de 2 barras.
- **Fix:** Crear skeletons específicos por página (document detail, dashboard, chat).

---

## 🟡 MEDIO — Mejoras importantes

| # | Área | Problema | Fix |
|---|------|----------|-----|
| ARCH-3 | Dead code | 15 aliases backward-compat en `agent.py:152-166` | Podar los no usados |
| ARCH-4 | N+1 queries | `document_graph.py:18-32` loops con queries individuales | Consolidar a JOINs |
| ARCH-5 | Testing | `document_graph.py`, `dates.py`, `redaction.py` sin tests | Añadir tests unitarios |
| SEC-4 | JWT | Sin revocación, token 12h sin refresh | Añadir refresh token o blacklist Redis |
| SEC-5 | Prompt injection | Pregunta del usuario no sanitizada antes del LLM | Añadir sanitización básica |
| SEC-6 | Integration JWT | Secret fallback a user JWT secret | Exigir `INTEGRATION_JWT_SECRET` separado |
| REL-5 | Idempotency | No hay guard al reintentar `process_document` | Check `job.status == 'processed'` al inicio |
| REL-6 | Watcher | Healthcheck solo verifica `isdir` | Verificar heartbeat file del watcher |
| REL-7 | Circuit breaker | No compartido entre workers | Aceptar (funciona por proceso) o usar Redis |
| UX-3 | ConfirmDialog | Sin manejo de ESC ni focus trap | Añadir keyboard handling WAI-ARIA |
| UX-4 | Sidebar | Entradas duplicadas "Duplicados" y "Cuarentena" → misma ruta | Unificar o diferenciar |
| UX-5 | Fonts | Google Fonts externos en cada carga | Self-host o preload |
| UX-6 | Work inbox | Hook duplicado en AppShell + Sidebar | Consolidar a un solo consumer |
| UX-7 | AdminSystem | 951 líneas, 8 useState, 12 queries | Descomponer en sub-componentes |
| UX-8 | Skip-to-content | No existe | Añadir link oculto para teclado |
| UX-9 | Chat a11y | Textarea sin aria-label, mensajes sin role="log" | Añadir ARIA |

---

## 🟢 BAJO — Incrementales

| # | Área | Problema |
|---|------|----------|
| ARCH-6 | Concurrency | `cached_property` en PaddleOCR depende de GIL (no explícito) |
| ARCH-7 | Dependencies | Sin lock file (poetry.lock / pip-compile) |
| ARCH-8 | API | Admin routes con prefijos inconsistentes |
| SEC-7 | Upload | Límites grandes (500MB/file, 2000 files/batch) |
| SEC-8 | Rate limit | Headers deshabilitados; default 200/min generoso |
| REL-8 | Backup | Scripts manuales, sin automatización, sin verificación de recencia |
| REL-9 | VRAM | Vision unload falla silenciosamente si shim no responde |

---

## Lo positivo (12 hallazgos buenos)

- Sin SQL injection (SQLAlchemy ORM + ILIKE escape)
- Token en httponly cookie (no localStorage)
- Defensa multi-capa contra prompt injection (regex + redaction + XML wrap)
- Path traversal prevenido (SHA256 hash storage)
- Validación multi-capa de archivos (extension + magic bytes + ejecutables)
- CORS restrictivo y ambient-aware
- PII redactada en logs de auth
- Tenant scope deny-by-default
- SQL-level scope enforcement
- CSP + security headers
- CSV formula injection protection
- Arquitectura de páginas bien descompuesta (F8b pattern)

---

## Orden de ejecución

| Fase | Tareas | Esfuerzo |
|------|--------|----------|
| **F1** Seguridad | SEC-1, SEC-2, SEC-3 (fuga de precios cross-tenant) | 3h |
| **F2** Fiabilidad | REL-1 (sweeper), REL-2 (commit transacción), REL-3 (temp files) | 4h |
| **F3** Monitoreo | REL-4 (métricas de fallos invisibles) | 3h |
| **F4** Arquitectura | ARCH-1 (vector dim), ARCH-3 (dead code), ARCH-4 (N+1) | 4h |
| **F5** Seguridad+ | SEC-4 (JWT refresh), SEC-5 (prompt sanitize), SEC-6 (integration secret) | 6h |
| **F6** UX | UX-1 (confirm), UX-2 (skeletons), UX-3 (dialog keyboard) | 5h |
| **F7** Testing | ARCH-5 (tests faltantes), REL-5 (idempotency guard) | 4h |
| **F8** Infra | REL-6 (watcher health), REL-8 (backup auto), ARCH-7 (lock file) | 4h |
| **F9** UX+ | UX-4 a UX-9 (mejoras menores) | 6h |
