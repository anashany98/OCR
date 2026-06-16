# Security Docker Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the verified P0/P1 data-leak, CI, and Docker/resource defects from the June 2026 audit.

**Architecture:** Centralize price redaction in one backend service, route all sensitive API/AI/search/business outputs through explicit mappers, and keep document-scope checks before response serialization or mutation. Split runtime container concerns by service profile and stop loading OCR/ML models in processes that do not process OCR.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic v2, pytest, React/Vite, Docker Compose, Celery, PostgreSQL/pgvector, Redis.

---

### Task 1: Central Business Redaction

**Files:**
- Create: `docu-intel/backend/app/services/business_redaction.py`
- Modify: `docu-intel/backend/app/services/redaction.py`
- Test: `docu-intel/backend/tests/test_security_redaction.py`

- [ ] **Step 1: Write failing tests**

Create tests that assert a scope without `can_view_prices` removes numeric amount fields, currencies, nested line prices, free-text amounts, and `source_path` for non-admin users.

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_security_redaction.py -v`
Expected: fails because `business_redaction` does not exist.

- [ ] **Step 3: Implement central redaction**

Add `redact_business_payload_for_scope`, `redact_record_for_scope`, and `redact_search_results_for_scope`. Reuse `redact_sensitive_text` for snippets.

- [ ] **Step 4: Verify**

Run: `pytest tests/test_security_redaction.py -v`
Expected: pass.

### Task 2: Sensitive Backend Routes

**Files:**
- Modify: `docu-intel/backend/app/api/routes/budgets.py`
- Modify: `docu-intel/backend/app/api/routes/orders.py`
- Modify: `docu-intel/backend/app/api/routes/invoices.py`
- Modify: `docu-intel/backend/app/api/routes/reconciliation.py`
- Modify: `docu-intel/backend/app/schemas/business.py`
- Modify: `docu-intel/backend/app/schemas/professional.py`
- Test: `docu-intel/backend/tests/test_security_redaction.py`

- [ ] **Step 1: Write failing API tests**

Add tests for users without `can_view_prices` against budgets, lines, orders, invoices, reconciliation, invoice creation with inaccessible `document_id`, and reconciliation mutation out of scope.

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_security_redaction.py -v`
Expected: failures show raw amounts or unauthorized mutation.

- [ ] **Step 3: Implement explicit response mappers**

Resolve `AccessScope`, filter records before serialization, and map ORM records to dicts through `redact_record_for_scope`.

- [ ] **Step 4: Verify**

Run: `pytest tests/test_security_redaction.py -v`
Expected: pass.

### Task 3: Search, Export, AI Resolved Documents, Aggregates

**Files:**
- Modify: `docu-intel/backend/app/api/routes/search.py`
- Modify: `docu-intel/backend/app/api/routes/ai.py`
- Modify: `docu-intel/backend/app/ai/agent.py`
- Modify: `docu-intel/backend/app/ai/context.py`
- Modify: `docu-intel/backend/app/tools/internal.py`
- Test: `docu-intel/backend/tests/test_security_redaction.py`

- [ ] **Step 1: Write failing tests**

Cover text/semantic/hybrid/export redaction, `/ai/ask`, `/ai/ask/stream`, persisted `resolved_document_json`, answer history readback, and `aggregate_business` without price permission.

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_security_redaction.py -v`
Expected: failures show raw excerpts or global aggregates.

- [ ] **Step 3: Implement redaction and scope passing**

Redact search results after scope filtering, sanitize export rows, redact `resolved_document` before persistence/SSE, and pass `AccessScope` into `aggregate_business`.

- [ ] **Step 4: Verify**

Run: `pytest tests/test_security_redaction.py -v`
Expected: pass.

### Task 4: CI Migrations Configuration

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `docu-intel/backend/app/core/config.py`
- Test: `docu-intel/backend/tests/test_config_validation.py`

- [ ] **Step 1: Write failing config tests**

Assert local defaults can import settings and non-local weak DB/JWT values fail clearly.

- [ ] **Step 2: Run tests to verify current CI mismatch**

Run: `pytest tests/test_config_validation.py -v`
Expected: failure for local default weak DB password.

- [ ] **Step 3: Fix CI values and local exception**

Use strong CI DB password and 64+ char secrets; keep production validation strict.

- [ ] **Step 4: Verify migrations**

Run: `alembic upgrade head`
Expected: settings validation no longer blocks migration.

### Task 5: Docker Profiles and Lazy OCR

**Files:**
- Modify: `docu-intel/docker-compose.yml`
- Modify: `docu-intel/backend/Dockerfile`
- Modify: `docu-intel/backend/Dockerfile.gpu`
- Modify: `docu-intel/backend/.dockerignore`
- Modify: `docu-intel/frontend/.dockerignore`
- Modify: `docu-intel/backend/app/core/config.py`
- Modify: `docu-intel/backend/app/workers/celery_app.py`
- Test: `docu-intel/backend/tests/test_ocr_init_warmup.py`

- [ ] **Step 1: Write failing lazy-load tests**

Assert non-OCR queues skip `preload_ocr_engine` by default and OCR queue can opt in.

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_ocr_init_warmup.py -v`
Expected: fails because preload is unconditional.

- [ ] **Step 3: Implement config and Compose profiles**

Add `ocr_engine_preload`, `pp_structure_enabled`, cache/model env vars, explicit images, profiles for GPU/PP-Structure, and improved ignores.

- [ ] **Step 4: Verify Docker config**

Run: `docker compose config`
Expected: valid compose; GPU workers behind profiles.

### Task 6: Frontend Redacted Amount Rendering

**Files:**
- Modify: `docu-intel/frontend/src/lib/utils.ts`
- Modify: `docu-intel/frontend/src/pages/BudgetsPage.tsx`
- Modify: `docu-intel/frontend/src/pages/OrdersPage.tsx`
- Modify: `docu-intel/frontend/src/pages/InvoicesPage.tsx`
- Modify: `docu-intel/frontend/src/pages/ReconciliationPage.tsx`
- Test: add focused frontend tests if existing test harness exposes page render utilities.

- [ ] **Step 1: Add helper tests**

Assert `formatMoney(null, { redacted: true })` renders `Oculto por permisos`.

- [ ] **Step 2: Implement helper and page usage**

Use the `prices_redacted` flag where backend sends it.

- [ ] **Step 3: Verify frontend**

Run: `npm test` and `npm run build`.

### Task 7: Final Verification

- [ ] Run backend targeted tests.
- [ ] Run `ruff check .`.
- [ ] Run `ruff format --check .`.
- [ ] Run `alembic upgrade head`.
- [ ] Run frontend lint/tests/build.
- [ ] Run `docker compose config`.
- [ ] Document completed fixes and remaining risks.
