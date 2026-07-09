# REMEDIACIÓN DEFINITIVA — Docu-Intel

> Documento de remediación ejecutable derivado de la auditoría arquitectónica del 2026-07-09.
> Cada problema incluye: **causa raíz, solución exacta (código/migración/comando) y verificación**.
> Stack: FastAPI + Celery + SQLAlchemy 2 + pgvector (backend) · React 18 + Vite + TanStack Query (frontend) · PostgreSQL 16 + Redis.
>
> **Convención:** toda migración nueva parte de `down_revision = "0041_delivery_notes"` (head actual).
> Aplica los cambios en orden de fase. Tras cada fase, ejecuta la verificación indicada antes de seguir.

---

## ÍNDICE

- [FASE 1 — Urgente (bloqueantes)](#fase-1--urgente-bloqueantes)
  - [F1.1 `documents.embedding` nunca migrado](#f11-documentsembedding-nunca-migrado)
  - [F1.2 Migración duplicada `0034` vs `0040`](#f12-migración-duplicada-0034-vs-0040)
  - [F1.3 `/metrics` expuesto sin autenticación](#f13-metrics-expuesto-sin-autenticación)
  - [F1.4 Workers GPU como root](#f14-workers-gpu-como-root)
  - [F1.5 Multi-tenant: tests deny-by-default en TODAS las rutas](#f15-multi-tenant-tests-deny-by-default-en-todas-las-rutas)
  - [F1.6 Limpieza de artefactos y config comprometida](#f16-limpieza-de-artefactos-y-config-comprometida)
- [FASE 2 — Importante (mantenibilidad + seguridad)](#fase-2--importante-mantenibilidad--seguridad)
- [FASE 3 — Escalabilidad](#fase-3--escalabilidad)
- [FASE 4 — Calidad](#fase-4--calidad)
- [VERIFICACIÓN GLOBAL](#verificación-global)

---

## FASE 1 — Urgente (bloqueantes)

Estos deben aplicarse **antes de seguir desarrollando**. Son defectos funcionales o de seguridad verificables en un despliegue limpio.

---

### F1.1 `documents.embedding` nunca migrado

**Causa raíz (verificada):** La recuperación vectorial a nivel documento consulta `d.embedding` (`backend/app/services/vector_store.py:175,201`), el pipeline escribe "en `Document.embedding`" (`backend/app/services/document_embedding_pipeline.py:99`) y `search_use_document_embedding=True` por defecto (`backend/app/core/config.py:289`). Pero **ninguna migración añade la columna** a `documents` (los únicos `add_column("documents")` son `budget_scope_id`, `quality_*`, `quality_flags_json`) y **el ORM `Document` no la declara** (`backend/app/models/document.py:29-76`). Resultado: en una BD nueva, `alembic upgrade head` + cualquier búsqueda document-level → `column "embedding" does not exist`.

**Solución — paso 1: nueva migración.** Crea `backend/alembic/versions/0042_document_level_embedding.py`:

```python
"""add documents.embedding + HNSW index (FASE 8.1 document-level retrieval)

Revision ID: 0042_document_level_embedding
Revises: 0041_delivery_notes
Create Date: 2026-07-09
"""
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision = "0042_document_level_embedding"
down_revision = "0041_delivery_notes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # La columna es nullable: los documentos existentes quedan sin embedding
    # hasta que el beat reembed (o un admin) los (re)procese.
    op.add_column("documents", sa.Column("embedding", Vector(768), nullable=True))
    op.add_column(
        "documents",
        sa.Column("embedding_model_version", sa.String(120), nullable=True),
    )
    op.create_index(
        "ix_documents_needs_reembedding_doc",  # ya existe a nivel chunk; distinto nombre
        "documents",
        ["needs_reembedding"],
        postgresql_where=sa.text("needs_reembedding IS TRUE"),
    )
    # HNSW parcial (solo filas con embedding). CONCURRENTLY no es posible
    # dentro de una transacción de migración; se crea en la misma transacción.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_documents_embedding_hnsw "
        "ON documents USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64) "
        "WHERE embedding IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_documents_embedding_hnsw")
    op.drop_index("ix_documents_needs_reembedding_doc", table_name="documents")
    op.drop_column("documents", "embedding_model_version")
    op.drop_column("documents", "embedding")
```

**Solución — paso 2: declarar en el ORM.** En `backend/app/models/document.py`, dentro de `class Document(Base)` (junto a `needs_reembedding`, ~línea 59):

```python
    # FASE 8.1 — embedding a nivel documento (un solo vector por documento,
    # fusionado con el signal por-chunk vía RRF). Nullable: se rellena en el
    # pipeline de embeddings. El índice HNSW lo crea la migración 0042.
    embedding: Mapped[Any | None] = mapped_column(Vector(768), nullable=True)
    embedding_model_version: Mapped[str | None] = mapped_column(String(120), nullable=True)
```

> Nota: `from typing import Any` y `from pgvector.sqlalchemy import Vector` ya están importados en el módulo (los usa `DocumentChunk`).

**Verificación:**
```bash
# 1. Sobre una BD vacía (contenedor throwaway):
docker compose run --rm migrate alembic downgrade base
docker compose run --rm migrate alembic upgrade head
docker compose exec postgres psql -U app -d docuintel -c "\d documents" | grep embedding
# 2. Test de contrato (añádelo, ver F1.5):
pytest backend/tests/test_openapi_contract.py -k document_embedding
```

---

### F1.2 Migración duplicada `0034` vs `0040`

**Causa raíz (verificada):** `0034_invoice_deterministic_fields.py` y `0040_invoice_fiscal_fields.py` añaden **los mismos campos** a `invoices` (`supplier_tax_id`, `taxable_base`, `vat_amount`), pero `0034` los declara `String(32)` y `0040` `String(50)` (el ORM `Invoice` dice `String(50)`, `professional.py:139`). En `alembic upgrade head` nuevo: `0034` crea `varchar(32)`, luego `0040` ejecuta `add_column` de columna ya existente → **error o tipo erróneo persistente**.

**Solución definitiva — editar `0034` (es una migración lineal pre-release; reescribirla es seguro):** elimina los `add_column` duplicados de `0034` (los añade `0040` a `String(50)`). Deja `0034` solo con lo que `0040` **no** añade. En `backend/alembic/versions/0034_invoice_deterministic_fields.py`, `upgrade()`:

```python
def upgrade() -> None:
    # NOTA: supplier_tax_id, taxable_base, vat_amount los añade 0040 a String(50)
    # (coincide con el ORM Invoice.supplier_tax_id). Esta migración solo añade
    # lo que 0040 no cubre. Si ya se aplicó en algún entorno, la migración
    # correctiva 0043 normaliza el ancho.
    op.execute("SELECT 1")  # no-op intencional para conservar la revisión en la cadena
```

**Solución — cinturón de seguridad: `0043` normaliza el tipo** (para entornos donde `0034` ya creó `varchar(32)`). Crea `backend/alembic/versions/0043_fix_invoice_supplier_tax_id_width.py`:

```python
"""ensure invoices.supplier_tax_id is varchar(50) (corrige 0034/0040)

Revision ID: 0043_fix_invoice_supplier_tax_id_width
Revises: 0042_document_level_embedding
"""
from alembic import op
import sqlalchemy as sa

revision = "0043_fix_invoice_supplier_tax_id_width"
down_revision = "0042_document_level_embedding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotente: ALTER TYPE es no-op si el tipo ya es varchar(50).
    op.alter_column(
        "invoices", "supplier_tax_id",
        existing_type=sa.String(32), type_=sa.String(50),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "invoices", "supplier_tax_id",
        existing_type=sa.String(50), type_=sa.String(32),
        existing_nullable=True,
    )
```

**Verificación:**
```bash
docker compose run --rm migrate alembic downgrade base
docker compose run --rm migrate alembic upgrade head   # no debe errorar
docker compose exec postgres psql -U app -d docuintel \
  -c "SELECT column_name, character_maximum_length FROM information_schema.columns \
      WHERE table_name='invoices' AND column_name='supplier_tax_id';"
# Esperado: supplier_tax_id | 50
```

---

### F1.3 `/metrics` expuesto sin autenticación

**Causa raíz (verificada):** `backend/app/services/metrics/endpoint.py:188-193` registra `@app.get("/metrics")` **sin `Depends`**. El backend publica `8000:8000` en `0.0.0.0` (`docker-compose.yml:55-56`). Expone conteos por estado, colas, estadísticas OCR, intentos de prompt-injection, tasas de cache.

**Solución preferida — red interna + no publicar puerto (Prometheus scrapea dentro de la red compose):**

En `docker-compose.yml`, servicio `backend`:
```yaml
  backend:
    ports: !reset []        # no publicar 8000 al host
    # (alternativa si necesitas exponerlo: "127.0.0.1:8000:8000")
```
Y deja que Prometheus (si lo añades) scrapee por el nombre de servicio `http://backend:8000/metrics` dentro de la red interna.

**Solución alternativa (si debe quedar expuesto) — auth por token interno estático:**

En `backend/app/core/config.py` añade:
```python
    metrics_token: str = ""  # vacío = requiere que el endpoint no esté expuesto al host
```
En `backend/app/services/metrics/endpoint.py`:
```python
from fastapi import Depends, Header, HTTPException
from app.core.config import settings

@app.get("/metrics")
def metrics(
    x_metrics_token: str | None = Header(default=None, alias="X-Metrics-Token"),
) -> Response:
    if settings.metrics_token and x_metrics_token != settings.metrics_token:
        raise HTTPException(status_code=401, detail="metrics token required")
    return Response(content=render_metrics(), media_type=CONTENT_TYPE_LATEST)
```

**Verificación:**
```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/metrics
# Con red interna (sin exponer): conexión rechazada desde el host = OK
# Con token: 401 sin header, 200 con X-Metrics-Token correcto
```

---

### F1.4 Workers GPU como root

**Causa raíz (verificada):** `backend/Dockerfile.gpu` no es multi-stage (deja `build-essential`/`python3.11-dev`), crea `appuser` pero nunca hace drop de privilegios (`backend/Dockerfile.gpu:64-89`), y `worker-heavy-gpu-0/1` en `docker-compose.yml:206-295` no definen `user:`.

**Solución — reescribir `backend/Dockerfile.gpu` a multi-stage + non-root** (esquema; conserva tus versiones exactas de CUDA/Paddle):

```dockerfile
# ---------- stage 1: builder ----------
FROM nvidia/cuda:12.6.3-cudnn-runtime-ubuntu22.04 AS builder
ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 python3.11-venv python3.11-dev build-essential curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*
RUN python3.11 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r /tmp/requirements.txt

# ---------- stage 2: runtime ----------
FROM nvidia/cuda:12.6.3-cudnn-runtime-ubuntu22.04 AS runtime
ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1 PATH="/opt/venv/bin:$PATH"
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 libgl1 libglib2.0-0 gosu tini \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd -g 10001 appuser && useradd -m -u 10001 -g 10001 appuser
COPY --from=builder /opt/venv /opt/venv
COPY backend/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
COPY backend/app /app/app
COPY backend/alembic.ini /app/alembic.ini
COPY backend/alembic /app/alembic
WORKDIR /app
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/docker-entrypoint.sh"]
CMD ["celery", "-A", "app.workers.celery_app", "worker", ...]
```

`docker-entrypoint.sh` ya hace el `gosu appuser` (conserva el del `Dockerfile` CPU). En `docker-compose.yml`, servicios GPU añade:
```yaml
    user: "10001:10001"
```

**Verificación:**
```bash
docker compose build worker-heavy-gpu-0
docker compose run --rm --no-deps worker-heavy-gpu-0 id   # uid=10001(appuser)
docker image inspect docu-intel-backend-gpu:latest \
  --format '{{.Config.User}}'   # 10001 (o vacío si entrypoint dropea; ok si gosu)
```

---

### F1.5 Multi-tenant: tests deny-by-default en TODAS las rutas

**Causa raíz (verificada):** el aislamiento multi-tenant vive **solo en código de aplicación** (`backend/app/services/tenant_access.py:672-698`, post-filtro en memoria) y la rama vectorial (`vector_store.py`) no aplica el scope por sí misma. Cualquier endpoint nuevo que olvide el filtro filtra cross-tenant. La corrección estructural (RLS) es **Fase 3**; aquí cerramos la brecha con un **test de contrato exhaustivo**.

**Solución — test parametrizado por ruta.** Amplía `backend/tests/test_tenant_deny_by_default.py` con un caso por ruta de negocio. Patrón:

```python
import pytest
from app.tenant_test_utils import two_tenants   # fixture: 2 hoteles + 1 user por hotel

BUSINESS_ROUTES = [
    ("GET",    "/api/v1/documents/{id}"),
    ("GET",    "/api/v1/documents/{id}/pages"),
    ("GET",    "/api/v1/budgets/{id}"),
    ("GET",    "/api/v1/orders/{id}"),
    ("GET",    "/api/v1/invoices/{id}"),
    ("GET",    "/api/v1/delivery-notes/{id}"),
    ("GET",    "/api/v1/plans/{id}"),
    ("PATCH",  "/api/v1/documents/{id}"),
    ("POST",   "/api/v1/documents/{id}/reprocess"),
    # añade aquí CADA ruta de lectura/escritura de un recurso por-id
]

@pytest.mark.parametrize("method,route_tmpl", BUSINESS_ROUTES)
def test_cross_tenant_access_denied(client, two_tenants, method, route_tmpl):
    """Un usuario del hotel A NO puede leer el documento del hotel B."""
    hotel_a_user, hotel_b_doc = two_tenants
    url = route_tmpl.format(id=hotel_b_doc.id)
    resp = client.request(method, url, headers=hotel_a_user.auth_header)
    assert resp.status_code == 404, (
        f"LEAK: {method} {url} devolvió {resp.status_code} a un usuario de otro tenant"
    )
```

> Regla de oro: **cada vez que se añada una ruta de negocio, se añade su caso a `BUSINESS_ROUTES`.** Considera un lint/check en CI que falle si una ruta declarada en el router no aparece en la lista.

**Verificación:**
```bash
pytest backend/tests/test_tenant_deny_by_default.py -v
```

---

### F1.6 Limpieza de artefactos y config comprometida

**Problemas:** (a) `frontend/vite.config.js` y `frontend/vite.config.d.ts` commiteados (`.js` es copia vieja divergente sin proxy `/api/v1` ni vitest); (b) `docker-compose.yml:341` tiene path de host Windows absoluto; (c) secretos débiles en `.env` local (no trackado, pero reales); (d) falta `frontend/.gitignore`.

**Solución:**
```bash
git rm docu-intel/frontend/vite.config.js docu-intel/frontend/vite.config.d.ts
```
En `docker-compose.yml`, línea ~341, sustituye el bind de host por un volumen nombrado o un comentario:
```yaml
    # ELIMINADO path de host absoluto. Para montar un folder de entrada,
    # usar un volumen nombrado o una variable: ${INPUT_DIR:-./data/input}:/app/data/input:ro
    - ./data/input:/app/data/input:ro
```
Crea `docu-intel/frontend/.gitignore`:
```
node_modules
dist
dist-ssr
coverage
*.local
.env
.env.*
!.env.example
*.tsbuildinfo
vite.config.js
vite.config.d.ts
```
Rota y refuerza secretos en `.env` (este archivo NO se commitea, pero aplica los cambios locales):
```bash
# Genera valores fuertes y pégalos en .env (NO en .env.example)
python -c "import secrets; print('JWT_SECRET='+secrets.token_urlsafe(64))"
python -c "import secrets; print('ADMIN_PASSWORD='+secrets.token_urlsafe(24))"
python -c "import secrets; print('PGADMIN_PASSWORD='+secrets.token_urlsafe(24))"
# HYPEREXTRACT_API_KEY: usar una key real, no 'lm-studio'
```

**Verificación:**
```bash
git ls-files docu-intel/frontend | grep "vite.config.js$"   # vacío = OK
git ls-files docu-intel/frontend | grep "vite.config.d.ts$"  # vacío = OK
git diff --cached --stat   # confirma los rm
```

---

## FASE 2 — Importante (mantenibilidad + seguridad)

### F2.1 Partir `ai/context.py` (1.636 LOC, god module)

**Causa raíz:** `collect_context` (`backend/app/ai/context.py:141-707`) es un `if/elif` de ~560 líneas sobre ~20 nombres de tool; mezcla dispatch + render + fallback fundamentado + builders por entidad.

**Solución — descomponer en 3 módulos:**

```
backend/app/ai/
├── context.py          # SOLO: ContextItem, GroundedResponse dataclasses + el punto de entrada delgado
├── tool_executor.py    # NUEVO: dispatch dict  {tool_name: handler}  (el if/elif -> dict)
├── grounding.py        # NUEVO: build_grounded_response, _build_friendly_fallback, dedupe_sources, clip_excerpt
└── renderers.py        # NUEVO: render_document_details, _render_structured_payload, _render_aggregate_table
                        #        + budget_context/order_context/document_context
```

Refactor núcleo — el `if/elif` a **dispatch dict**:
```python
# tool_executor.py
from typing import Callable
from app.tools import internal

ToolHandler = Callable[..., "ContextItem"]

TOOL_HANDLERS: dict[str, ToolHandler] = {
    "get_budget_total":      internal.get_budget_total,
    "get_budget_lines":      internal.get_budget_lines,
    "get_order_status":      internal.get_order_status,
    # ... una entrada por cada tool
}

def run_tool(tool, db, user_scope) -> ContextItem | None:
    handler = TOOL_HANDLERS.get(tool.name)
    if handler is None:
        return None
    return handler(db=db, scope=user_scope, **tool.args)
```
`context.collect_context` queda en ~40 líneas iterando `tools` → `run_tool`.

**Verificación:** `pytest backend/tests/test_ai_agent_refactor.py backend/tests/test_chat_structured_tools_natural.py -v` (deben pasar sin cambios de comportamiento).

---

### F2.2 Partir `services/business_extraction.py` (1.476 LOC)

**Solución — 3 módulos:**
```
backend/app/services/business/
├── extractors.py   # _detect_company_name, _tax_id, _total_amount, _parse_markdown_table, _parse_amount
├── persistence.py  # persist_business_extraction + _add_entities_for_budget/order/invoice/delivery_note
├── linking.py      # _find_related_budget_id, _find_related_order_id
└── vlm.py          # _try_vlm_table_extraction  (mover a vision_manager a medio plazo)
```
Mantén una fachada `business_extraction.py` que re-exporte para no romper imports existentes:
```python
# backend/app/services/business_extraction.py  (fachada thin)
from app.services.business.persistence import persist_business_extraction
from app.services.business.extractors import *
# ... re-exports
```

---

### F2.3 Sacar lógica de negocio de los routers grandes

- `admin_operations.py`: mueve `work_inbox` (L221-393) y `work_inbox_action` (L479-618) a `services/inbox.py`; el handler queda como `return inbox_service.work_inbox(db, user, params)`.
- `plans.py`: mueve `suggest_rooms` (L470-572) + helpers `_describe_plan_page`/`_run_plan_vision_sync` + `_VISION_PROMPT` a `services/vision_manager.py`.
- `documents.py`: mueve `reclassify_documents` (L191-268) a `services/classification.py` (ya existe el módulo).

**Verificación:** los tests de integración (`test_integration_api.py`, `test_e2e_demo.py`) cubren estos endpoints; deben seguir en verde.

---

### F2.4 Handler global de excepciones + `request_id` por contextvar

**Problema:** `main.py` solo maneja `RateLimitExceeded`; 100 `HTTPException` a mano; hay `except Exception: pass` (`documents.py:220`) que silencia errores.

**Solución — en `backend/app/core/errors.py` (nuevo):**
```python
class DomainError(Exception):
    status_code: int = 400
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        if status_code:
            self.status_code = status_code

class NotFoundError(DomainError):
    status_code = 404

class ForbiddenError(DomainError):
    status_code = 403

class ConflictError(DomainError):
    status_code = 409
```

**`request_id` por contextvar** en `backend/app/middleware/request_id.py` (añade el binding):
```python
import contextvars
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        rid = request.headers.get("X-Request-ID") or uuid4().hex
        token = request_id_var.set(rid)
        request.state.request_id = rid
        try:
            resp = await call_next(request)
        finally:
            request_id_var.reset(token)
        resp.headers["X-Request-ID"] = rid
        return resp
```
Y en `core/logging.py`, un processor que inyecte `request_id_var.get()` en cada registro.

**Handler global** en `main.py`:
```python
from fastapi import Request
from fastapi.responses import JSONResponse
from app.core.errors import DomainError
import logging, structlog
logger = structlog.get_logger("app.errors")

@app.exception_handler(DomainError)
async def domain_error_handler(request: Request, exc: DomainError):
    return JSONResponse(status_code=exc.status_code,
                        content={"detail": str(exc), "request_id": request.state.request_id})

@app.exception_handler(Exception)
async def unhandled_handler(request: Request, exc: Exception):
    logger.exception("unhandled_error", request_id=getattr(request.state, "request_id", "-"))
    return JSONResponse(status_code=500,
                        content={"detail": "internal error",
                                 "request_id": getattr(request.state, "request_id", "-")})
```
Sustituye los `except Exception: pass` por `except Exception: logger.warning("...", exc_info=True)`.

**Verificación:** `curl` a un endpoint que lance `NotFoundError` → 404 con `request_id` en el body y en logs.

---

### F2.5 Corregir los dos N+1 verificados

**(a) `services/operations.py:187-196`** — COUNT por documento en bucle. Reemplaza por un único `GROUP BY`:
```python
from sqlalchemy import select, func
from app.models import ExtractionJob

# Pre-fetch: set de document_ids con job activo (1 query en vez de N)
active_doc_ids = {
    row[0]
    for row in db.execute(
        select(ExtractionJob.document_id, func.count())
        .where(ExtractionJob.status.in_(["pending", "processing"]))
        .group_by(ExtractionJob.document_id)
    )
}
for document in documents:
    if active_jobs >= settings.ingestion_max_pending_jobs:
        skipped += len(documents) - len(job_ids) - skipped
        break
    if document.id in active_doc_ids:
        skipped += 1
        continue
    # ... reprocess_document(...)
```

**(b) `api/routes/documents.py:223-235`** — acceso lazy a `doc.pages`:
```python
from sqlalchemy.orm import selectinload
documents = list(
    db.scalars(
        select(Document)
        .options(selectinload(Document.pages))   # 1 query extra (IN), no N
        .where(Document.deleted_at.is_(None))
        .limit(limit)
    ).all()
)
```

**Verificación:** con `echo=True` en `SessionLocal`, confirma que el nº de queries es constante (no crece con el nº de documentos).

---

### F2.6 Decidir sobre `mv_active_documents` (refrescada pero nunca leída)

**Verificado:** solo `REFRESH ... CONCURRENTLY` en `workers/tasks.py:165-191`; ningún `SELECT FROM` en el código.

**Solución (elige una):**
- **Opción A — usarla:** en `api/routes/documents.py` listado, consulta `mv_active_documents` (ya filtra `deleted_at IS NULL`) en vez de la tabla `documents`.
- **Opción B — eliminar:** borra el beat task y crea `0044_drop_mv_active_documents.py` con `op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_active_documents")`. (Recomendada si el listado no tiene cuello de botella.)

**Verificación:** `grep -rn "mv_active_documents" backend/app/` → debe mostrar solo lecturas (A) o nada (B).

---

### F2.7 Frontend — adoptar `queryKeys.ts` (hoy es código muerto)

**Verificado:** `frontend/src/lib/queryKeys.ts` (83 LOC) **no es importado por ningún archivo**; ~40 claves inline.

**Solución — migrar hook a hook.** Ejemplo en `frontend/src/pages/InvoicesPage.tsx`:
```ts
// ANTES
const { data } = useQuery({ queryKey: ["invoices", query], queryFn: () => api.invoices.list(query) });
// DESPUÉS
import { queryKeys } from "@/lib/queryKeys";
const { data } = useQuery({
  queryKey: queryKeys.invoices.list(query),
  queryFn: () => api.invoices.list(query),
});
```
Amplía `queryKeys.ts` para cubrir todos los dominios (`invoices`, `budgets`, `documents`, `auditLogs`, `system.health`, etc.). En las mutaciones, invalida con `queryClient.invalidateQueries({ queryKey: queryKeys.invoices.all })`.

**Verificación:** `grep -rn "queryKey: \[" frontend/src | wc -l` debe tender a 0.

---

### F2.8 Frontend — interceptor de 401 (expiración de sesión)

**Problema:** `frontend/src/api/core.ts` no maneja 401; al expirar la cookie, el usuario queda bloqueado.

**Solución — en `core.ts`:**
```ts
let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(cb: () => void) { onUnauthorized = cb; }

export async function request<T>(...): Promise<T> {
  // ... fetch existente
  if (res.status === 401) {
    onUnauthorized?.();   // useAuth.tsx registra: limpia user + navigate("/login")
    throw new ApiError(401, "session expired");
  }
  // ...
}
```
En `useAuth.tsx`, al montar: `setUnauthorizedHandler(() => { setUser(null); window.location.href = "/login"; })`.

**Verificación:** manual — dejar expirar la cookie y verificar redirect automático.

---

### F2.9 `/healthz` real (verifique DB + Redis) sin auth

**Problema:** `/health` es estático (`main.py:107-109`); el healthcheck de compose lo usa → un backend sin DB sigue "sano".

**Solución — añade un endpoint sin auth distinto del público:**
```python
# main.py
from app.database.session import SessionLocal
from app.services.healthchecks import check_db, check_redis  # ya existen sondas

@app.get("/healthz")
def healthz() -> dict:
    db = SessionLocal()
    try:
        checks = {"db": check_db(db), "redis": check_redis()}
    finally:
        db.close()
    ok = all(c["ok"] for c in checks.values())
    return {"status": "ok" if ok else "degraded", "checks": checks}

# /health se mantiene como liveness ligero (sin dependencias) para restart rápido
```
En `docker-compose.yml`, separa liveness vs readiness:
```yaml
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://localhost:8000/healthz"]
```

**Verificación:** para Postgres → el healthcheck debe pasar a `unhealthy`.

---

### F2.10 Revisión menor: `delete_document` debe llamar `can_access_document`

En `backend/app/api/routes/documents.py:397-406`, añade el check defensivo aunque sea admin (defensa en profundidad):
```python
doc = db.get(Document, document_id)
if not doc or doc.deleted_at: raise HTTPException(404)
if not can_access_document(db, doc, resolve_user_access_scope(db, current_user)):
    raise HTTPException(404)
```

---

## FASE 3 — Escalabilidad

### F3.1 Multi-tenant a nivel de DATO (RLS de PostgreSQL)

**Objetivo:** que la BD **garantice** el aislamiento aunque la app olvide el filtro.

**Paso 1 — migración `0045_documents_tenant_columns.py`:**
```python
def upgrade() -> None:
    op.add_column("documents", sa.Column("hotel_id", sa.BigInteger(), nullable=True))
    op.add_column("documents", sa.Column("chain_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key("fk_documents_hotel", "documents", "hotels", ["hotel_id"], ["id"])
    op.create_foreign_key("fk_documents_chain", "documents", "hotel_chains", ["chain_id"], ["id"])
    op.create_index("ix_documents_hotel_chain", "documents", ["chain_id", "hotel_id"])
    # Backfill desde document_access_metadata (1 hotel/cadena por documento, el "owner")
    op.execute("""
        UPDATE documents d SET
          hotel_id = dam.hotel_id,
          chain_id = dam.chain_id
        FROM document_access_metadata dam
        WHERE dam.document_id = d.id AND dam.is_owner = TRUE
    """)
```
(Requiere añadir `is_owner`/lógica de propietario en `document_access_metadata`; si no existe, define el propietario como el hotel de la primera regla `FolderAssignmentRule` que coincida.)

**Paso 2 — activar RLS y políticas:**
```sql
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents FORCE ROW LEVEL SECURITY;

-- App se conecta como rol 'app' BYPASS; un rol 'app_tenant' aplica el filtro:
CREATE POLICY documents_tenant_isolation ON documents
  USING (
    chain_id = current_setting('app.tenant_chain', true)::bigint
    OR hotel_id = current_setting('app.tenant_hotel', true)::bigint
  );
```
La app, por request, hace `SET LOCAL app.tenant_chain = :chain` dentro de la sesión para el scope resuelto del usuario.

**Paso 3 — refactor** `tenant_access.py` para establecer el `SET LOCAL` al abrir la sesión (en `api/deps.py:get_db`) en vez de (o además de) la reescritura de query.

> **Rollout seguro:** despliega RLS en modo *audit* (policy `USING (true) WITH CHECK (...)`) primero; monitoriza; luego endurece. Mantén los tests de F1.5 como red de seguridad.

**Verificación:** los tests deny-by-default deben seguir pasando; añade un test que haga `db.execute(text("SET ROLE app_tenant"))` + `SELECT` y verifique que solo ve su tenant.

---

### F3.2 Back-pressure cuando `ocr_heavy` satura

**Problema:** sin back-pressure real; el cliente recibe timeouts sin saber que la cola está saturada.

**Solución:** expone la profundidad de cola (ya en `/metrics`) en un endpoint `/api/v1/system/congestion` (autenticado) y, cuando `ocr_heavy` > umbral, el endpoint de upload/reprocess devuelve **503 con `Retry-After`**. Frontend muestra un banner "Sistema saturado, reintenta en Xs".

```python
# ingestion.py / document_workflow.py
depth = get_queue_depth("ocr_heavy")
if depth > settings.ocr_heavy_congestion_threshold:
    raise HTTPException(503, headers={"Retry-After": "60"}, detail="ocr queue saturated")
```

---

### F3.3 Caché de embeddings de query y de transformación

**Problema:** cada pregunta lanza embedding de query + HyDE/multi-query (N llamadas LLM) sin caché.

**Solución:** en `search_service.py`, cachea por hash de query:
```python
from app.services.ai_cache import get_cache  # ya existe ai_cache.py
cache = get_cache()
qhash = hashlib.sha256(query.encode()).hexdigest()
cached = cache.get(f"qemb:{qhash}")
if cached is None:
    cached = embed_text(query)
    cache.set(f"qemb:{qhash}", cached, ttl=300)
query_embedding = cached
```
Igual para las variantes multi-query.

---

### F3.4 Confirmar `partition_tasks` en el beat schedule

**Verificado:** `backend/app/workers/partition_tasks.py` **existe** (corrige el temor inicial de que faltara). Acción: confirmar que la tarea está registrada en `celery_app.py` `beat_schedule` (mensual). Si no lo está, añadirla o los INSERT en `audit_logs`/`extraction_jobs` fallarán al agotarse las 6 particiones seeded.

**Verificación:** `celery -A app.workers.celery_app inspect registered | grep partition`; revisar `celery_app.py` `beat_schedule`.

---

### F3.5 JSON → JSONB donde se hace lookup + GIN

**Problema:** todas las columnas JSON son `JSON` (no `JSONB`); la única query de path (`operations.py:173`) paga un cast por fila sin índice.

**Migración `0046_jsonb_lookup_columns.py`** (solo las que se consultan: `quality_flags_json`, `tags_json`, `permissions_json`):
```python
op.alter_column("documents", "quality_flags_json",
                postgresql_using="quality_flags_json::jsonb", type_=sa.dialects.postgresql.JSONB())
op.create_index("ix_documents_quality_flags_gin", "documents", ["quality_flags_json"],
                postgresql_using="gin")
```

---

## FASE 4 — Calidad

### F4.1 Generar tipos frontend desde OpenAPI

**Problema:** `frontend/src/types/api.ts` (868 LOC) está escrito a mano; tipos `Plan` duplicados y divergentes (`types/api.ts:688-726` vs `api/plans.ts:3-41`).

**Solución:**
```bash
cd docu-intel/frontend
npm i -D openapi-typescript
# genera desde el openapi.json del repo
npx openapi-typescript ../docs/openapi.json -o src/types/api.generated.ts
```
Reemplaza los tipos manuales por `import type { components } from "./api.generated"; type Plan = components["schemas"]["Plan"];`. Elimina `api/plans.ts` tipos duplicados.

**Verificación:** `tsc --noEmit` sin errores; `grep` de tipos `Plan` manuales → 0.

---

### F4.2 Unificar duplicados de UI

- `StatusBadge`: elimina la copia de `pages/admin/system-sections.tsx:38` y `LearningStatusBadge` → usa el canónico `components/layout/StatusBadge.tsx`.
- `Tabs`/`SelectPill` en `pages/ocr-review/components.tsx:496-556` → usa `components/ui/tabs.tsx` (Radix, con a11y de teclado).
- CSV export: `InvoicesPage.tsx:45-76` y `chat/useChat.ts:403-413` → llamar a `lib/exportCsv.ts`.

---

### F4.3 Partir `useChat.ts` (579 LOC, 6 tareas)

Extrae: `chatExport.ts` (CSV/markdown), `chatStorage.ts` (localStorage/sesiones), y mueve el **parseo regex de la respuesta del LLM** (`useChat.ts:444-449`, parsea `**Respuesta:**`) a un campo estructurado del contrato backend (el agente ya devuelve JSON estructurado; úsalo en vez de parsear prosa con regex).

---

### F4.4 CI: SAST, escaneo de dependencias/imagen, SBOM, pin por digest

En `docu-intel/.github/workflows/ci.yml` añade jobs:
```yaml
  security:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: aquasecurity/trivy-action@master
        with: { image-ref: docu-intel-backend:latest, severity: "HIGH,CRITICAL" }
      - run: pip install bandit pip-audit && bandit -r backend/app -q && pip-audit
      - run: cd frontend && npm audit --audit-level=high
```
Pinnea todas las imágenes base por digest (`image@sha256:...`) en Dockerfiles y compose.

---

### F4.5 Backups automatizados + restore drill

- Programa `scripts/backup.ps1` vía Task Scheduler/cron del host (o un contenedor `backup` en compose con `restart: unless-stopped` y un entrypoint que duerma + ejecute).
- Copia offsite cifrada (S3/Restic) tras cada backup.
- **Restore drill en CI** semanal: levanta stack throwaway, restaura el último backup, corre smoke tests.

---

### F4.6 JWT con librería vetada (opcional, medio plazo)

Sustituye el JWT casero HS256 (`core/security.py:78-167`) por `pyjwt` (o `python-jose`), manteniendo la separación de propósitos (`typ`) y exigiento `typ` siempre. Reduce riesgo criptográfico.

---

## VERIFICACIÓN GLOBAL

Checklist final tras aplicar las 4 fases:

```bash
# 1. Backend: lint + tipos + tests con gate de cobertura
cd docu-intel/backend && ruff check . && mypy app && pytest --cov-fail-under=70

# 2. BD limpia desde cero (verifica F1.1, F1.2, F3.1, F3.5)
docker compose down -v
docker compose run --rm migrate alembic upgrade head          # no errora
docker compose exec postgres psql -U app -d docuintel -c "\d documents" | grep -E "embedding|hotel_id"

# 3. Contract tests (incl. tenant deny-by-default exhaustivo)
pytest backend/tests/test_openapi_contract.py backend/tests/test_tenant_deny_by_default.py -v

# 4. Seguridad operativa
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/metrics    # 401/403 o rechazo
docker compose run --rm worker-heavy-gpu-0 id                          # uid=10001
curl -fsS http://localhost:8000/healthz                                 # 200 con db+redis ok

# 5. Frontend
cd docu-intel/frontend && npm run lint && npm test && npm run build
grep -rn "queryKey: \[" src | wc -l                                    # → 0
npx tsc --noEmit                                                       # sin errores
```

---

## RESUMEN DE ARCHIVOS A CREAR/MODIFICAR

| Acción | Archivo |
|---|---|
| Crear migración | `backend/alembic/versions/0042_document_level_embedding.py` |
| Crear migración | `backend/alembic/versions/0043_fix_invoice_supplier_tax_id_width.py` |
| Crear migración | `backend/alembic/versions/0044_drop_mv_active_documents.py` *(si Opción B)* |
| Crear migración | `backend/alembic/versions/0045_documents_tenant_columns.py` |
| Crear migración | `backend/alembic/versions/0046_jsonb_lookup_columns.py` |
| Editar migración | `backend/alembic/versions/0034_invoice_deterministic_fields.py` |
| Editar modelo | `backend/app/models/document.py` (+ `embedding`, `embedding_model_version`) |
| Editar config | `backend/app/core/config.py` (+ `metrics_token`) |
| Crear | `backend/app/core/errors.py` |
| Editar | `backend/app/main.py` (handlers globales + `/healthz`) |
| Editar | `backend/app/middleware/request_id.py` (contextvar) |
| Editar | `backend/app/services/metrics/endpoint.py` (auth `/metrics`) |
| Reescribir | `backend/Dockerfile.gpu` (multi-stage non-root) |
| Editar | `docker-compose.yml` (puerto, `user:` GPU, path host) |
| Refactor | `backend/app/ai/context.py` → `tool_executor.py` + `grounding.py` + `renderers.py` |
| Refactor | `backend/app/services/business_extraction.py` → `business/{extractors,persistence,linking,vlm}.py` |
| Editar | `backend/app/services/operations.py` (N+1) |
| Editar | `backend/app/api/routes/documents.py` (N+1, delete scope) |
| Editar | `frontend/src/lib/queryKeys.ts` + todos los hooks (adopción) |
| Editar | `frontend/src/api/core.ts` (401) |
| Crear | `frontend/.gitignore` |
| Eliminar | `frontend/vite.config.js`, `frontend/vite.config.d.ts` |
| Crear | `frontend/src/types/api.generated.ts` (codegen) |

---

*Documento generado el 2026-07-09 a partir de la auditoría arquitectónica verificada.
Aplica por fases y verifica cada bloque antes de avanzar. Si lo prefieres, puedo aplicar yo mismo los arreglos de **Fase 1** (bloqueantes) sobre el código.*
