# Production Hardening Followup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the immediate production blockers found after the full project review.

**Architecture:** Keep PostgreSQL + pgvector as the source of truth and push budget scope into query filters where available. Cache entries must include the effective access scope so permission changes or different principals do not share answer/search state accidentally.

**Tech Stack:** FastAPI, SQLAlchemy, pytest, PowerShell, GitHub Actions, React/Vite.

---

### Task 1: Budget Scope Search Hardening

**Files:**
- Modify: `backend/app/services/search_service.py`
- Modify: `backend/app/services/integration_tools.py`
- Test: `backend/tests/test_backlog_sprints.py`

- [x] Write a failing test showing `search_text(..., filters={"budget_scope_id": id})` excludes documents from other budget scopes.
- [x] Write a failing integration test where many out-of-scope results appear before the in-scope result and `limit=1` still returns the signed scope result.
- [x] Add `budget_scope_id` support to `_apply_document_filters`.
- [x] Inject signed `budget_scope_id` into integration search filters before calling search services.
- [x] Run the targeted tests and confirm they pass.

### Task 2: Access-Scoped Cache

**Files:**
- Modify: `backend/app/services/ai_cache.py`
- Modify: `backend/app/services/tenant_access.py`
- Modify: `backend/app/ai/agent.py`
- Modify: `backend/app/api/routes/search.py`
- Test: `backend/tests/test_backlog_sprints.py`

- [x] Write a failing test proving AI cache keys differ by access scope.
- [x] Add a stable access scope cache signature.
- [x] Include that signature in AI answer cache keys.
- [x] Include a non-SQL `_cache_scope` marker in user search filters for cache separation.
- [x] Run the targeted tests and confirm they pass.

### Task 3: Backup Verification And CI

**Files:**
- Create: `scripts/verify-backup.ps1`
- Create: `.github/workflows/ci.yml`
- Modify: `README.md`
- Modify: `docs/production-runbook.md`
- Test: `backend/tests/test_backlog_sprints.py`

- [x] Write a failing test for a backup verification script against a sample backup directory.
- [x] Implement `verify-backup.ps1` to validate `docuintel.dump`, `files/`, and `manifest.json`.
- [x] Write a failing test requiring CI to run Alembic, backend tests, frontend tests, and frontend build.
- [x] Add the GitHub Actions workflow.
- [x] Document the verification command in README and the production runbook.

### Task 4: Page-Level OCR Reprocess

**Files:**
- Modify: `backend/app/services/document_service.py`
- Modify: `backend/app/api/routes/admin.py`
- Modify: `backend/app/services/quality.py`
- Test: `backend/tests/test_ocr_review.py`
- Test: `backend/tests/test_phase5_operations.py`

- [x] Write a failing endpoint test proving page OCR review creates `reprocess:ocr_page:<page_number>` instead of full OCR.
- [x] Write a failing service test proving only the selected page text/blocks are replaced.
- [x] Implement `reprocess_document_page`.
- [x] Add `ocr_page` job mode parsing and processing.
- [x] Mark a failed page as `page_failed`/`needs_human_review` without marking the whole document as failed.
- [x] Run targeted OCR and phase operation tests.
