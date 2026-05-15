# Budget Scope Sessions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add budget/presupuesto scope isolation for the integration API, leaving hotel/cadena isolation parked for a future project.

**Architecture:** A `BudgetScope` represents one presupuesto/carpeta principal. Documents can be assigned to one scope, integration clients get explicit `api_client_budget_scopes` permissions, and the external app obtains a short-lived signed session token tied to one `budget_scope_id`. Existing hotel/cadena access remains in the codebase for later but is not the primary integration boundary for this phase.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, Pydantic, PostgreSQL/SQLite tests, JWT/HMAC signing, Celery ingestion hooks.

---

## File Structure

- Create: `backend/app/models/budget_scope.py` for `BudgetScope` and `ApiClientBudgetScope`.
- Modify: `backend/app/models/__init__.py` to export the new models.
- Modify: `backend/app/models/document.py` to add nullable `documents.budget_scope_id`.
- Create: `backend/alembic/versions/0006_budget_scopes.py` with tables, FK and indexes.
- Create: `backend/app/services/budget_scope.py` for code extraction from paths, assignment, permission checks and signed session payloads.
- Modify: `backend/app/services/integration_security.py` to carry optional session scope in `IntegrationContext`.
- Modify: `backend/app/services/integration_tools.py` to filter by session `budget_scope_id` and to let session permission override price visibility safely.
- Modify: `backend/app/api/routes/integrations.py` to add `POST /integrations/v1/sessions` and audit session creation.
- Modify: `backend/app/services/document_service.py` and `backend/app/ingestion/scanner.py` to assign scopes from source paths when possible.
- Modify: `backend/app/schemas/integration.py` to add session request/response contracts.
- Test: `backend/tests/test_budget_scope_sessions.py`.
- Docs: `.env.example`, `README.md`, and this plan.

---

### Task 1: Tests for Budget Scope Sessions

**Files:**
- Create: `backend/tests/test_budget_scope_sessions.py`

- [ ] **Step 1: Write failing tests**

Add tests that seed two scopes, two documents and two budgets. Test:

```python
def test_session_requires_explicit_budget_scope_permission():
    # Missing api_client_budget_scopes row returns 403.
    # Existing row with can_query=True returns a signed session token.
```

```python
def test_session_token_filters_budget_lookup_to_one_scope():
    # Same budget number in two scopes returns the document from the session scope only.
```

```python
def test_session_permission_hides_prices_even_for_price_policy():
    # Technician policy can see prices, but api_client_budget_scopes.can_see_amounts=False redacts prices.
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
python -m pytest backend/tests/test_budget_scope_sessions.py -q
```

Expected: failure because `BudgetScope`, `/integrations/v1/sessions`, and budget-scope filtering do not exist yet.

---

### Task 2: Models and Migration

**Files:**
- Create: `backend/app/models/budget_scope.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/models/document.py`
- Create: `backend/alembic/versions/0006_budget_scopes.py`

- [ ] **Step 1: Add SQLAlchemy models**

Create:

```python
class BudgetScope(Base):
    __tablename__ = "budget_scopes"
```

with `budget_code`, folder fields, status counters and timestamps.

Create:

```python
class ApiClientBudgetScope(Base):
    __tablename__ = "api_client_budget_scopes"
```

with `api_client_id`, `budget_scope_id`, `can_query=True`, `can_see_amounts=False`.

- [ ] **Step 2: Add document FK**

Add nullable `Document.budget_scope_id` so old data remains valid.

- [ ] **Step 3: Add Alembic migration**

Create the two tables, indexes, unique `(api_client_id, budget_scope_id)` and `documents.budget_scope_id` FK/index.

- [ ] **Step 4: Run tests and verify model import**

Run:

```bash
python -m pytest backend/tests/test_budget_scope_sessions.py -q
```

Expected: tests advance to endpoint/security failures instead of model import failures.

---

### Task 3: Scope Service and Signed Sessions

**Files:**
- Create: `backend/app/services/budget_scope.py`
- Modify: `backend/app/schemas/integration.py`
- Modify: `backend/app/api/routes/integrations.py`
- Modify: `backend/app/services/integration_security.py`

- [ ] **Step 1: Implement service helpers**

Functions:

```python
extract_budget_code_from_path(path: str | None) -> str | None
ensure_budget_scope(db, budget_code: str, source_path: str | None = None) -> BudgetScope
assign_document_budget_scope(db, document: Document) -> BudgetScope | None
get_client_budget_permission(db, client_id: int, budget_scope_id: int) -> ApiClientBudgetScope | None
create_budget_session_token(client_id: int, technician_id: str, budget_scope_id: int, can_see_amounts: bool) -> str
decode_budget_session_token(token: str) -> BudgetSessionClaims
```

- [ ] **Step 2: Add Pydantic contracts**

Add:

```python
class IntegrationSessionCreateRequest(BaseModel):
    budget_code: str

class IntegrationSessionCreateResponse(BaseModel):
    session_token: str
    budget_code: str
    budget_scope_id: int
    expires_in: int
    can_see_amounts: bool
```

- [ ] **Step 3: Add session endpoint**

Implement `POST /integrations/v1/sessions`:

1. authenticate API key and technician;
2. require `read` scope;
3. resolve exact `budget_code`;
4. require `api_client_budget_scopes.can_query=True`;
5. return signed token with `can_see_amounts`;
6. audit success/failure-relevant metadata without leaking secrets.

- [ ] **Step 4: Decode optional session in integration context**

If `Authorization: Bearer <token>` is present, validate client id, technician id and expiry, then attach `budget_scope_id` and `can_see_amounts` to `IntegrationContext`.

---

### Task 4: Tool Filtering and Redaction

**Files:**
- Modify: `backend/app/services/integration_tools.py`

- [ ] **Step 1: Filter budget tools by session scope**

For `get_budget_by_number` and `search_budgets`, join through `Document.budget_scope_id` when context has a session scope.

- [ ] **Step 2: Filter document/search tools by session scope**

For `search_documents`, `hybrid_search`, `get_document`, `get_document_blocks`, entities, plans and related documents, exclude records whose document does not match the session scope.

- [ ] **Step 3: Make price visibility safe**

When session is present:

```python
can_view_prices = session.can_see_amounts and existing_policy_allows_prices
```

When no session is present, keep current behavior for backward compatibility.

- [ ] **Step 4: Add scope metadata to responses**

Include `budget_scope_id` and `budget_code` in `response.scope` when a session is active.

---

### Task 5: Ingestion Assignment

**Files:**
- Modify: `backend/app/services/document_service.py`
- Modify: `backend/app/ingestion/scanner.py`

- [ ] **Step 1: Assign scope on register**

After `Document` is flushed, call `assign_document_budget_scope()` using `source_path`.

- [ ] **Step 2: Keep existing folder/hotel metadata untouched**

Do not remove `apply_folder_rules_to_document()` or tenant tables. They remain future-compatible but secondary.

- [ ] **Step 3: Add source path extraction behavior**

Support:

```text
/data/input/presupuestos/245745/file.pdf -> 245745
/srv/docuintel/inbox/245745/sub/file.pdf -> 245745
integration upload with budget_code -> explicit budget_code
```

---

### Task 6: Verification and Docs

**Files:**
- Modify: `README.md`
- Modify: `.env.example`

- [ ] **Step 1: Document the new flow**

Document:

```text
POST /integrations/v1/sessions
Authorization: Bearer session_token
budget_scope_id isolation
prices hidden by default
```

- [ ] **Step 2: Run focused tests**

Run:

```bash
python -m pytest backend/tests/test_budget_scope_sessions.py -q
```

- [ ] **Step 3: Run integration tests**

Run:

```bash
python -m pytest backend/tests/test_integration_api.py backend/tests/test_tenant_access.py -q
```

- [ ] **Step 4: Run full backend tests**

Run:

```bash
python -m pytest backend/tests -q
```

- [ ] **Step 5: Build frontend**

Run:

```bash
cd frontend
npm run build
```

---

## Execution Notes

- Keep hotel/cadena code in place but do not extend it in this phase.
- Do not make Qdrant mandatory yet. The current vector backend can stay pgvector/local; the budget scope contract must be storage-independent.
- Do not expose SQL to the external IA.
- Do not make prices visible by default.
- Preserve backward compatibility for existing `/integrations/v1/tools/execute` calls without a session until the external app migrates.
