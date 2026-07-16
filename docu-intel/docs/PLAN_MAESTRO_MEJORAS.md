# PLAN MAESTRO DE MEJORAS — Docu-Intel

> Brief de ejecución para aplicar las mejoras verificadas en la rama
> `codex/integracion-ovisocr2`. Documento **autocontenido**: un agente de
> código (MiniMax u otro) puede ejecutarlo sin contexto adicional.
>
> **Fecha de auditoría de código:** 2026-07-16 · **Entorno objetivo:** desarrollo
> local (los bloqueantes de despliegue a producción quedan fuera de alcance,
> listados en Fase 7).
>
> **IMPORTANTE — todos los estados están verificados contra el código real de la
> rama, no contra los documentos de planificación previos (varios estaban
> desactualizados y marcaban como "PENDIENTE" trabajo que ya está hecho).**

---

## Cómo usar este documento

1. Ejecuta las fases en orden (0 → 1 → 2 → …). Cada fase es independiente salvo
   la Fase 0, que **debe** ejecutarse antes que cualquier fix.
2. Para cada ítem encontrarás: **Archivo objetivo**, **Problema** (con cita
   `archivo:línea`), **Solución** (con snippet de código concreto),
   **Verificación** (comando ejecutable) y **Criterio de salida**.
3. Marca el checklist `[ ]` → `[x]` al terminar cada ítem.
4. Antes de "re-abrir" un ítem, consulta el **Anexo A**: tabla de cosas que YA
   están hechas y no deben tocarse.

## Reglas de ejecución obligatorias (para MiniMax/agentes)

- **Commits aislados y atomizados.** Un commit = un fix, con scope claro
  (`fix(search): …`, `fix(celery): …`, `feat(ai): …`). Nunca mezcles fases en
  un mismo commit.
- **No acumules el árbol sucio.** Si hay más de ~10 archivos modificados sin
  commitear, para y haz commit antes de seguir.
- **No reimplementes lo ya hecho.** Revisa el Anexo A antes de tocar nada.
- **Cada fix va con su test.** Prioriza tests que no requieran GPU/DB para que
  corran en CI local. Usa los patrones existentes en `backend/tests/`.
- **Estilo:** FastAPI + SQLAlchemy 2.0 (`select()`), Pydantic v2, settings
  tipados en `core/config.py`. Respeta densidad de comentarios e idiom del
  código circundante.
- **No hagas `git push` ni cambies de rama** salvo instrucción explícita del
  usuario. Los commits se generan en la rama actual.
- **No elimines docstrings ni comentarios** de los módulos `app/ai/*` (ya hubo
  una pasada que los borró masivamente — debe revertirse en la Fase 0).

---

# FASE 0 — Estabilizar el árbol de trabajo 🔴 (PREVIO A TODO)

**Contexto:** hay 386 archivos modificados sin commitear (+53k / −28k líneas) que
mezclan (a) eliminación masiva de docstrings/comentarios del módulo `app/ai/`,
con (b) funcionalidad nueva (OvisOCR2, CAD/DXF-DWG, migraciones) en 33 archivos
sin trackear. Esto hace que cualquier fix sea difícil de revertir y de revisar.

## 0.1 Revertir la eliminación de docstrings/comentarios del módulo IA

- [ ] Listar los archivos de `backend/app/ai/` cuyo diff SOLO elimina
  documentación (cabeceras de arquitectura, docstrings de función, comentarios
  "Why this split", etc.):
  ```bash
  git diff --stat HEAD -- docu-intel/backend/app/ai/
  # Inspecciona ejemplos: agent.py pierde toda la cabecera de arquitectura
  git diff HEAD -- docu-intel/backend/app/ai/agent.py
  ```
- [ ] Para cada archivo cuyo diff sea **solo** eliminación de docs, restaurarlo:
  ```bash
  git checkout HEAD -- docu-intel/backend/app/ai/<archivo>
  ```
  **Cuidado:** si un archivo mezcla borrado de docs CON cambio funcional,
  рестáuralo completo (`git checkout HEAD -- …`) y luego re-aplica SOLO el
  cambio funcional de forma limpia. Verifica con `git diff` que el resultado
  final conserva la documentación original.
- [ ] Verificar que el backend sigue importando correctamente:
  ```bash
  cd docu-intel && python -c "import app.ai.agent, app.ai.context, app.ai.prompts, app.ai.tools, app.ai.validation"
  ```

## 0.2 Commit segmentado de la funcionalidad nueva

- [ ] **Commit OvisOCR2:**
  ```bash
  git add docu-intel/backend/app/ocr/ovisocr2.py \
    docu-intel/backend/app/ocr/ovisocr2_output.py \
    docu-intel/backend/app/ocr/tier4_chain.py \
    docu-intel/backend/app/ocr/routing.py \
    docu-intel/backend/app/ocr/factory.py \
    docu-intel/services/ \
    docu-intel/backend/tests/test_ovisocr2_*.py \
    docu-intel/backend/tests/fixtures/ovisocr2/ \
    docu-intel/scripts/ovisocr2* docu-intel/scripts/*ovisocr2* \
    docu-intel/scripts/certify_ovisocr2.ps1 \
    docu-intel/docs/runbooks/ \
    docu-intel/artifacts/ovisocr2/ \
    docu-intel/docker-compose.yml
  git commit -m "feat(ocr): integración OvisOCR2 Tier 4 (feature flag off)"
  ```
- [ ] **Commit CAD/DXF-DWG:**
  ```bash
  git add docu-intel/backend/alembic/versions/0062_cad_structured_extraction.py \
    docu-intel/backend/tests/fixtures/cad/ \
    docu-intel/backend/tests/test_cad_structured_implementation.py \
    docu-intel/backend/tests/test_plan_cad_safety.py \
    docu-intel/scripts/benchmark_cad_ingestion.py \
    docu-intel/scripts/reprocess_cad_documents.py \
    docu-intel/scripts/certify_cad.ps1 \
    docu-intel/docs/PLAN_IMPLEMENTACION_DXF_DWG_COMPRENSION_IA.md
  git commit -m "feat(ocr): extracción estructurada CAD (DXF/DWG)"
  ```
- [ ] **Commit migración AI fallback reason:**
  ```bash
  git add docu-intel/backend/alembic/versions/0063_ai_answer_fallback_reason.py
  git commit -m "feat(ai): motivo de fallback de respuesta"
  ```
- [ ] **Commit docker test:**
  ```bash
  git add docu-intel/docker-compose.test.yml docu-intel/backend/Dockerfile.test
  git commit -m "chore(docker): compose test y Dockerfile.test"
  ```
- [ ] **Commit informe de pruebas reales:**
  ```bash
  git add docu-intel/docs/INFORME_PRUEBAS_REALES_INGESTA_Y_IA_2026-07-15.md
  git commit -m "docs: informe de pruebas reales de ingesta e IA"
  ```
- [ ] Revisar lo que quede (`git status`) y agrupar el resto en commits con
  scope claro. Si un cambio no es claramente funcional ni de doc, descríbelo al
  usuario antes de commitear.

## 0.3 Verificación final de la Fase 0

- [ ] `git status` queda limpio o con cambios deliberados mínimos.
- [ ] `cd docu-intel && ruff check backend` sin errores nuevos.
- [ ] `cd docu-intel && pytest backend/tests -q -k "not gpu and not integration"`
      pasa (o al menos no empeora respecto a HEAD).

**Criterio de salida Fase 0:** árbol limpio, historial legible, cada cambio
reversible aisladamente, documentación del módulo IA restaurada.

---

# FASE 1 — Bugs críticos y bloqueantes 🔴 (FOCO INICIAL)

## 1.1 Fuga de permisos en `/exact` y `/guided`

- **Estado:** PARCIAL
- **Archivo objetivo:** `backend/app/api/routes/search.py`
- **Problema:** `search_text` SÍ aplica `access_scope` en SQL previo
  (`backend/app/services/search_service.py:127-131`), pero:
  - `/exact` (`search.py:53-127`) hace `select(Budget|Order|DocumentEntity)`
    **sin** `apply_access_predicates` y filtra solo post-hoc con
    `filter_search_results_for_scope` (`search.py:127`). El `LIMIT` se aplica
    **antes** del filtro de scope → puede filtrar fuera de scope y descartar
    resultados válidos.
  - `/guided` (`search.py:146`) llama a `search_text(db, normalized, limit=limit)`
    **sin** el argumento `access_scope`.
- **Solución:**
  1. En `/exact`, para cada rama (`budget`, `order`, `client`/`supplier`,
     `reference`/etc.): unir al `document_id` y aplicar el predicado de scope
     **antes** del `LIMIT`. Reutiliza el helper existente `apply_access_predicates`
     de `services/search_service.py`. Ejemplo patrón para Budget:
     ```python
     from app.services.search_service import apply_access_predicates
     from app.models.document import Document

     stmt = select(Budget).join(Document, Document.id == Budget.document_id)
     stmt = apply_access_predicates(stmt, scope)
     budgets = db.scalars(stmt.where(Budget.budget_number == normalized).limit(limit)).all()
     ```
     Repetir el `.join(Document, Document.id == <ent>.document_id)` +
     `apply_access_predicates(stmt, scope)` en las ramas `order`, `entities` y
     en los `ilike` de `client`/`supplier`.
  2. En `/guided` (`search.py:146`):
     ```python
     results = search_text(db, normalized, limit=limit, access_scope=scope)
     ```
  3. Conservar `filter_search_results_for_scope` como defense-in-depth.
- **Verificación:**
  ```bash
  cd docu-intel && pytest backend/tests -q -k "exact_search or guided"
  ```
- **Test a añadir:** en `backend/tests/test_search_*.py`, caso con dos usuarios
  de scope distinto → el endpoint `/exact` devuelve solo resultados del scope
  permitido; con un `LIMIT` bajo, no se "comen" el cupón resultados ajenos.
- [ ] Hecho · Commit: `fix(search): aplicar access_scope en SQL previo de /exact y /guided`

## 1.2 Bug de la cola asíncrona de embeddings (Celery)

- **Estado:** CONFIRMADO
- **Archivo objetivo:** `backend/app/services/document_processing_core.py`
  (función `_celery_broker_available`, líneas 60-78)
- **Problema:** `connection_or_acquire()` devuelve un **context manager**, no
  una conexión. El uso actual es incorrecto:
  ```python
  conn = celery_app.connection_or_acquire()   # conn es el CM, no la conexión
  with conn:
      conn.ensure_connection(max_retries=0, timeout=2.0)  # opera sobre el CM
      return True
  ```
  Comportamiento frágil/dependiente de versión de Celery: puede marcar el broker
  como no disponible incorrectamente → se descarta el encolado de
  `embed_document_task` (`document_processing_core.py:891` y `:1057`) y de
  hyperextract (`:89-107`, mismo helper) → fuerza re-embebido manual admin.
- **Solución:**
  ```python
  def _celery_broker_available() -> bool:
      """Quick check if the Celery broker (Redis) is reachable."""
      import os
      if os.environ.get("CELERY_ALWAYS_EAGER") or os.environ.get("TESTING"):
          return False
      try:
          from app.workers.celery_app import celery_app
          with celery_app.connection_or_acquire() as conn:
              conn.ensure_connection(max_retries=0, timeout=2.0)
              return True
      except Exception:
          return False
  ```
- **Verificación:**
  ```bash
  cd docu-intel && pytest backend/tests -q -k "broker or celery"
  # Tras levantar Redis: la ingesta debe encolar embeddings automáticamente
  # (sin re-embebido manual). Buscar en logs "embed_document_task" encolado.
  ```
- **Test a añadir:** con broker simulado (o `CELERY_ALWAYS_EAGER`), verificar
  que `_celery_broker_available()` devuelve `False` en tests y que en dev con
  Redis vivo devuelve `True`.
- [ ] Hecho · Commit: `fix(celery): usar connection_or_acquire como context manager`

## 1.3 Redacción PII antes del LLM (IBAN / NIF / CIF / NIE / email / teléfono)

- **Estado:** PARCIAL — redacción de importes hecha y gated por permisos
  (`backend/app/services/redaction.py`, `backend/app/ai/context.py:427-446`,
  `backend/app/ai/agent.py:298,404`). **Ausente por completo** para
  identificadores personales: grep `iban|nif|dni|cif|email` en `backend/app/ai/`
  y `services/redaction.py` = 0 patrones de redacción.
- **Archivos objetivo:** `backend/app/services/redaction.py`,
  `backend/app/ai/context.py`
- **Problema:** IBAN, NIF/DNI/NIE/CIF, emails y teléfonos llegan en claro al
  prompt del LLM dentro de los context items.
- **Solución:**
  1. Ampliar `services/redaction.py` con regexes (reusar el patrón de
     `redact_sensitive_text`):
     ```python
     PII_REDACTION = "[DATO OCULTO]"

     IBAN_RE = re.compile(r"\b(?:ES)?\d{2}(?:[\s-]?\d{4}){5}\d{3}\b", re.IGNORECASE)
     DNI_NIE_RE = re.compile(r"\b[XXYZ]\d{7,8}[A-Z]\b")
     CIF_RE = re.compile(r"\b([ABCDEFGHJUV]\d{8})([A-Z])\b")
     EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
     PHONE_RE = re.compile(r"(?:\+34[\s-]?)?(?:\b[6789]\d{8}\b)")
     ```
  2. Aplicar en `redact_sensitive_text` (o en una nueva
     `redact_pii(text)`) tras las redacciones de dinero.
  3. Llamarla desde `redact_context_items_for_scope` (`ai/context.py`) de forma
     análoga a la redacción de importes (gated por permiso; con flag para roles
     autorizados que puedan ver PII, p.ej. `access_scope.can_view_pii` si existe,
     o siempre-on si se decide redacción universal).
- **Verificación:**
  ```bash
  cd docu-intel && pytest backend/tests -q -k "redact or pii"
  ```
- **Test a añadir:** texto con `"IBAN ES91 2100 0418 4502 0005 1332"` y
  `"NIF 12345678A"` y `"correo@dominio.es"` → queda redactado a `[DATO OCULTO]`
  antes de construir el prompt.
- [ ] Hecho · Commit: `feat(ai): redactar PII (IBAN/NIF/CIF/email/teléfono) antes del LLM`

**Criterio de salida Fase 1:** los 3 fixes con tests verdes; `/exact`+`/guided`
filtran scope en SQL; la ingesta encola embeddings automáticamente; ningún
IBAN/NIF/email llega en claro al prompt.

---

# FASE 2 — Seguridad y permisos (completar) 🟠

## 2.1 Rate limiting en `/documents` y `/search/guided`

- **Estado:** `slowapi` configurado (`backend/app/core/rate_limit.py`),
  cubre `/search/*`, `/ai/*`, `/auth/login`. **`routes/documents.py` no tiene
  ningún `@limiter`**; `/search/guided` tampoco.
- **Archivo objetivo:** `backend/app/api/routes/documents.py`,
  `backend/app/api/routes/search.py`
- **Solución:** importar `limiter` y añadir decoradores con políticas sensatas:
  - upload → `@limiter.limit("30/minute")`
  - list/get → `@limiter.limit("120/minute")`
  - reprocess → `@limiter.limit("10/minute")`
  - download → `@limiter.limit("30/minute")`
  - `/search/guided` → `@limiter.limit("60/minute")`
- **Verificación:**
  ```bash
  cd docu-intel && grep -n "@limiter" backend/app/api/routes/documents.py
  # Debe mostrar un decorador por endpoint sensible.
  ```
- [ ] Hecho · Commit: `feat(api): rate limit en /documents y /search/guided`

## 2.2 Reflejar unicidad contextual de `BudgetScope` en el ORM

- **Estado:** PARCIAL. La BD tiene el índice único contextual creado por
  migración raw (`backend/alembic/versions/0053_contextual_budget_identity.py:28`),
  pero el modelo `BudgetScope` (`backend/app/models/budget_scope.py:18`) **no**
  declara `UniqueConstraint` en `__table_args__`. Si se regenera el schema desde
  el ORM, se pierde la restricción.
- **Archivo objetivo:** `backend/app/models/budget_scope.py`
- **Solución:** añadir a `BudgetScope.__table_args__` un `UniqueConstraint`
  acorde a la migración 0053:
  ```python
  from sqlalchemy import UniqueConstraint
  __table_args__ = (
      UniqueConstraint(
          "year", "brand_id", "hotel_id", "budget_code",
          name="uq_budget_scope_context",
      ),
  )
  ```
  Ajustar columnas/condición (`legacy_unscoped`) para que coincida con la
  migración raw. **No requiere migración nueva** (ya existe en BD).
- **Verificación:**
  ```bash
  cd docu-intel && python -c "from app.models.budget_scope import BudgetScope; print(BudgetScope.__table__.constraints)"
  ```
- [ ] Hecho · Commit: `fix(models): reflejar unicidad contextual de BudgetScope en el ORM`

**Criterio de salida Fase 2:** rate-limit en todos los endpoints sensibles;
modelo ORM coherente con la BD.

---

# FASE 3 — Rendimiento y experiencia del chat/RAG 🟠

**Diagnóstico real (ya hecho — NO reabrir):** QueryPlan anti-fan-out ✅
(`multi_query.py:60-119`), exact-first ✅ (`context.py:644,983`), caché de
respuesta AI pre-contexto ✅ (`ai.py:220-289`), caché de búsqueda ✅,
reformulación anidada desactivada por defecto ✅ (`search_allow_nested_expansion=False`).

## 3.1 SSE verdaderamente inmediato

- **Estado:** NO CUMPLE. `routes/ai.py` construye todo el contexto síncrono
  (`collect_context` en `ai.py:314-317`, + gates, grounded response,
  serialización `ai.py:356-429`) **antes** de devolver el `StreamingResponse`,
  que luego emite `event: status {"state":"retrieval"}` (`ai.py:443-449`).
  Resultado: el cliente no ve nada hasta que termina la recuperación.
- **Archivo objetivo:** `backend/app/api/routes/ai.py` (endpoint `/ask/stream`)
- **Solución:** refactor para que el **primer chunk** sea inmediato
  (`event: status {"state":"retrieval"}`) y `collect_context(...)` se ejecute
  **dentro** del generador (lazy), no antes del `StreamingResponse`. Mantener
  el camino de cache-hit inmediato ya existente (`ai.py:252-289`).
- **Verificación:** medir tiempo al primer byte del stream (debe ser <500ms) con
  una petición real `/ai/ask/stream`.
- [ ] Hecho · Commit: `perf(chat): emitir SSE de status antes de la recuperación`

## 3.2 Activar y validar el reranker (o confirmar off por diseño)

- **Estado:** BGE-reranker-v2-m3 vía CrossEncoder, GPU con fallback CPU,
  aplicado 1× en `_apply_rerank_and_mmr`
  (`backend/app/services/search_service.py:410-445`) ✅ — **pero
  `search_reranker_enabled=False` por defecto** (`backend/app/core/config.py:456`).
  En local no corre.
- **Solución:** medir latencia p50/p95 con y sin reranker en dev; si es
  aceptable, activar por config (`search_reranker_enabled=True`) en `.env` de
  dev; documentar la decisión. Garantizar el guard de candidatos
  (`MIN_CANDIDATES_FOR_RERANK`).
- **Verificación:** comparar tiempo de `/search/hybrid` y calidad de top-k con
  flag on/off sobre un conjunto de queries de prueba.
- [ ] Hecho · Commit: `perf(search): activar/medir reranker` (o `docs:` si se decide off)

## 3.3 Single-flight cache para búsquedas idénticas concurrentes

- **Estado:** AUSENTE. No hay dedupe de queries idénticas en vuelo en
  `context.py` ni `search_service.py`.
- **Solución:** añadir un mapa `query_key -> Future`/`threading.Event` en el
  servicio de búsqueda para coalescer peticiones idénticas concurrentes. Reusar
  el patrón del commit `2062ff6` ("coalesce identical cold requests") si aplica
  a nivel IA.
- **Verificación:** test con N llamadas concurrentes idénticas → el backend
  ejecuta 1 recuperación y sirve N respuestas.
- [ ] Hecho · Commit: `perf(search): single-flight para queries idénticas concurrentes`

## 3.4 (Opcional) Revisar coste de HyDE

- HyDE (`search_service.py:190-218`) añade 1 embed extra por query (sin LLM).
  Si tras 3.1–3.3 la latencia sigue alta, evaluar
  `search_query_transform_strategy="none"` para preguntas factuales vía el
  QueryPlan. **Opcional, medir antes de decidir.**

**Criterio de salida Fase 3:** primer evento SSE <500ms; p50/p95 de respuesta
antes/después documentados en `docs/`.

---

# FASE 4 — Calidad OCR y extracción (deuda) 🟡

> La mayoría de `FIXES_PRIORITARIOS.md` ya está hecha (ver Anexo A).
> Queda:

## 4.1 Verificar score `_quality` real en cascada

- **Estado:** los docs dicen "ya hecho según audit". **Verificar** que
  `backend/app/ocr/cascading.py` selecciona el tier por **score de calidad**
  (confianza + cobertura + estructura) y no por longitud de texto.
- **Acción:** si sigue por longitud, implementar score ponderado; si ya está por
  calidad, cerrar el ítem con evidencia.
- [ ] Verificado · Commit: `feat(ocr): score _quality en cascada` (solo si cambia)

## 4.2 Logging/métricas de fallos Tier 2/3

- **Estado:** silenciados según FIX-4.
- **Archivo objetivo:** `backend/app/ocr/cascading.py`
- **Solución:** añadir log estructurado + métrica Prometheus cuando
  Tesseract→Paddle o Paddle→Tier4 cae **por fallo** (excepción), distinguiendo
  del descenso **por calidad**.
- [ ] Hecho · Commit: `feat(ocr): metricas de fallo de tier`

## 4.3 Job de re-OCR + re-embed de baja confianza

- **Archivo objetivo:** `backend/app/commands/backfill_reprocess.py`
- **Solución:** conectar el comando existente a un job periódico del
  `worker-maintenance` que reprocese documentos con `confidence < umbral`
  configurable (tras confirmar 4.1).
- [ ] Hecho · Commit: `feat(maintenance): job periódico de re-OCR de baja confianza`

**Criterio de salida Fase 4:** métricas de fallback de tier visibles; job de
reproceso de baja confianza operando con umbral configurable.

---

# FASE 5 — Frontend / UX 🟡

## 5.1 Overlays de planos en el visor genérico de documento

- **Estado:** PARCIAL. Los overlays funcionan
  (`frontend/src/pages/plano/usePlanOverlays.ts`, `PlanoAnnotationPage.tsx`)
  pero **solo en la ruta dedicada** `documents/:id/annotate-plan`
  (`frontend/src/routes/router.tsx:215-218`). El visor genérico
  `DocumentDetailPage` (`frontend/src/pages/document/`) **no los integra**
  (grep `plano|overlay|usePlanOverlays` en `pages/document/` = 0).
- **Solución:** embeber un modo "ver anotaciones de plano" dentro de
  `DocumentDetailPage` cuando `document.document_type === "plano"`, reutilizando
  `usePlanOverlays`.
- [ ] Hecho · Commit: `feat(viewer): overlays de plano en la ficha de documento`

## 5.2 `npm run test` y cobertura

- **Estado:** `npm run test` cae por cobertura (PLAN_TERRA punto 17).
- **Solución:** ajustar el umbral de cobertura de Vitest a uno realista o
  excluir archivos puramente generados, para que el gate pase.
- **Verificación:** `cd docu-intel/frontend && npm run test` verde.
- [ ] Hecho · Commit: `chore(frontend): umbral de cobertura realista`

## 5.3 (Backlog UX — fuera de esta ronda)

`manualChunks` en Vite, visor OpenSeadragon, snap-to-line: listados como deuda.

**Criterio de salida Fase 5:** overlays visibles desde la ficha de documento
plano; `npm run test` verde.

---

# FASE 6 — OvisOCR2: decisión y certificación (opcional) 🔵

La integración está completa en código pero **desactivada y sin certificar**
(`ovisocr2_enabled=False`, canary 0%, `baseline.json` no generado). No bloquea
dev local.

**Decisión a tomar antes de ejecutar:** (a) certificar ahora si hay GPU
disponible, o (b) dejar congelada con feature flag y seguir con Fases 1–5.

Si se certifica:

- [ ] **6.1** Generar `baseline.json` real con `scripts/certify_ovisocr2.ps1
  --dry-run` primero, luego benchmark real con servicio levantado.
- [ ] **6.2** Soak test de 200 páginas sin OOM/crash.
- [ ] **6.3** Promoción del canary 5%→25%→100% **solo sobre páginas elegibles**
  (nunca 100% de todas), manteniendo Dots/NuExtract en cada paso; rollback
  ensayado (no solo documentado).
- [ ] **6.4** Fijar SLO p95 en RTX 4070; documentar matriz de configuración
  dev/canary/prod y la guía de actualización del modelo en
  `docs/runbooks/ovisocr2.md`.

**Criterio de salida Fase 6:** baseline + soak + decisión de promoción
documentada, o feature flag dejado en off con justificación.

---

# FASE 7 — Deuda técnica y observabilidad (backlog, sin ejecución inmediata) 🔵

Listado para documentar; **no ejecutar salvo petición explícita**:

- Backfill completo del corpus (31.323 archivos) — hoy probado solo con 50.
- Particionado de `audit_logs` / `extraction_jobs`.
- Sentry con PII scrubbing; bcrypt obligatorio (hoy fallback PBKDF2 silencioso).
- Golden dataset OCR + pipeline RAGAS + métricas Prometheus por tier con
  dashboard Grafana.
- Logging estructurado con `request_id` / `correlation_id`.
- Dependencias obsoletas: PaddleOCR 2.x→3.x (incompatible), Celery 5.6+.

### Bloqueantes de despliegue a PRODUCCIÓN — FUERA DE ALCANCE (entorno = dev local)

Se reapertura cuando el objetivo sea producción (Coolify/Linux):

- **B1:** eliminar `host.docker.internal` de `docker-compose.prod.yml` y
  `.env.production.example`; añadir servicio `llama-server`.
- **B2:** bind-mounts → named volumes en prod compose + documentar `chown`.
- **B3:** sacar `alembic upgrade head` del CMD del backend (job/sidecar
  `migrate`), no race-safe con réplicas.
- **B4:** `worker-heavy` (CPU) en perfil por defecto, no `--profile ocr-cpu`.
- Backups/restore Linux/Coolify probados end-to-end.

---

# ANEXO A — Ítems que YA están hechos · NO reabrir

Verificado contra el código de la rama `codex/integracion-ovisocr2` (2026-07-16).
Antes de tocar cualquiera de estos, confirma con código; si ya están, **cierra**
el ítem sin re-implementar.

| Ítem | Evidencia |
|------|-----------|
| Migración `plans.project_phase` | `alembic/versions/0038_plans_project_phase_revision.py:24-27`; head `0063`. Ya creada y vigente. |
| Ingesta crea `DocumentOccurrence.project_id` + `DocumentBudgetLink` | `services/document_registration_service.py:482,565,585-595` |
| `ImageAnalysis` + `classify_image_multilabel()` conectados | `services/image_analysis_service.py:52` ← `document_processing_core.py:1212` |
| `technical_pipeline.py` conectado y persiste | `document_processing_core.py:1242-1266` |
| Preprocesado OCR por motor | `ocr/preprocess.py` (`preprocess_adaptive`, variantes por motor); llamado desde tesseract/paddle/pp_structure; DotsOCR usa `preprocess_for_manuscript` |
| `InvoiceLine` persistidas | `services/business_extraction.py:492-502` ← `document_processing_core.py:1219` |
| Clasificación MSG→email, XLSX→excel | `services/classification.py:633-645` |
| Bug regex `invoice_date_missing` (fechas textuales ES) | `services/dates.py:48-82,156-194`; `find_dates_in_text` reconoce "15 de enero de 2026" |
| Redacción de importes antes del LLM (gated) | `services/redaction.py`; `ai/context.py:427-446`; `ai/agent.py:298,404` |
| `EMBEDDING_FALLBACK_TO_HASH` no existe (política fail-fast) | `core/config.py:376-381`; `services/document_embedding_pipeline.py:42-46,60-67` |
| Cookies httponly + samesite + secure-auto | `api/routes/auth.py:49-57,63-68`; `config.py:575-576` |
| CORS sin wildcard en producción | `app/main.py:127-152`; `config.py:802-823` |
| Validación MIME uploads por magic bytes | `services/file_security.py:62-96` (hand-rolled, no python-magic) |
| Rate-limit en `/search/*`, `/ai/*`, `/auth/login` | `core/rate_limit.py`; `routes/search.py`, `routes/ai.py`, `routes/auth.py` |
| QueryPlan anti-fan-out + exact-first + cachés | `ai/multi_query.py:60-119`; `ai/context.py:1131-1175`; `routes/ai.py:220-289` |
| Reformulación anidada desactivada por defecto | `config.py:450` (`search_allow_nested_expansion=False`) |
| Unicidad contextual `BudgetScope` en BD (raw) | `alembic/versions/0053_contextual_budget_identity.py:28` |
| Integración OvisOCR2 (código, feature flag off) | `ocr/ovisocr2*.py`, `tier4_chain.py`, `routing.py`, `factory.py`, `services/ovisocr2/` |

---

# Secuencia de ejecución (resumen)

```
FASE 0  estabilizar árbol (revert docstrings + commits segmentados)
   └─ FASE 1  3 bugs críticos (permisos /exact·guided · Celery · PII)
        └─ FASE 2  rate-limit /documents + ORM BudgetScope
             └─ FASE 3  SSE inmediato · reranker · single-flight
                  └─ FASE 4  OCR quality/log/job
                       └─ FASE 5  frontend overlays + cobertura
                            └─ FASE 6/7  OvisOCR2 (opcional) · backlog
```

Cada fix se entrega con su test y se commitea de forma aislada. Tras cada fase,
actualiza los checklists `[x]` de este documento.
