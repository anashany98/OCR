# Production Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one backend-first hardening pass for practical permissions, data quality, production readiness, and large-volume operations.

**Architecture:** Implement focused backend services and admin endpoints, then wire minimal UI panels. Reuse existing `tenant_access`, `quality`, `queue_control`, and admin route patterns. Tests are written first for each behavior.

**Tech Stack:** FastAPI, SQLAlchemy 2, Pydantic, pytest, React, TypeScript, React Query, Docker Compose.

---

### Task 1: Backend Contracts And Tests

**Files:**
- Create: `backend/tests/test_production_hardening_plus.py`
- Modify: `backend/app/schemas/admin.py`

- [ ] Write failing tests for effective permissions, quality summary/actions, readiness, file integrity, paginated operations, and bulk tag assignment.
- [ ] Run `python -m pytest backend\tests\test_production_hardening_plus.py -q` and confirm missing endpoints fail.
- [ ] Add Pydantic contracts for the tested responses.
- [ ] Re-run targeted tests.

### Task 2: Backend Services And Endpoints

**Files:**
- Create: `backend/app/services/access_review.py`
- Create: `backend/app/services/data_quality.py`
- Create: `backend/app/services/production_readiness.py`
- Modify: `backend/app/api/routes/admin.py`
- Modify: `backend/app/api/routes/documents.py`

- [ ] Implement effective access review using existing access scope resolution.
- [ ] Implement quality rule summary and recalculation helpers.
- [ ] Implement production readiness and file integrity checks.
- [ ] Add admin endpoints for permissions, quality, readiness, integrity, and document tag bulk updates.
- [ ] Add paginated admin operations endpoint.
- [ ] Run targeted backend tests green.

### Task 3: Frontend UI And Client Tests

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/types/api.ts`
- Modify: `frontend/src/api/client.test.ts`
- Modify: `frontend/src/pages/AdminPage.tsx`

- [ ] Write failing frontend client tests for new endpoints.
- [ ] Add types and client methods.
- [ ] Add UI sections in Administración for readiness, integrity, quality and permission review.
- [ ] Run `npm run test -- --run` and `npm run build`.

### Task 4: Full Verification

**Files:**
- Modify: `README.md`
- Modify: `docs/production-runbook.md`

- [ ] Update docs with new endpoints and operational checks.
- [ ] Run `python -m pytest backend\tests -q`.
- [ ] Run `npm run test -- --run`.
- [ ] Run `npm run build`.
- [ ] Run `docker compose up -d --build`.
- [ ] Smoke readiness, quality, access review and frontend route.
