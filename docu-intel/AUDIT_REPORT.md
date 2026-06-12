# Docu-Intel Repository Audit

Audit date: 2026-06-11  
Repository root audited: `C:\Users\PC\Desktop\PROYECTOS\OCR\docu-intel`

## A) Coverage Inventory

I opened the attached request and then reviewed the repository from disk. The audit sweep opened every text/config file returned by `rg --files docu-intel` and skipped only binary/media fixtures.

| Area | Files opened | Notes |
|---|---:|---|
| `backend/app` | 208 | API routes, OCR engines, parsers, AI agent/context/client, services, models, schemas, workers, ingestion, tools. |
| `backend/tests` | 159 | Unit/integration/performance tests relevant to OCR, tenant access, embeddings, workflows, integrations, frontend API client fixtures. |
| `alembic` | 32 | Migration chain, env, versions. |
| `frontend/src` | 118 | Router, shell/sidebar, admin routes, chat, document pages, work inbox, plans, hooks, API clients, types. |
| `frontend` config | 13 | `package.json`, Vite, TS configs, ESLint, Prettier, Tailwind, lockfile. |
| root/config/scripts/docs | 45 | Compose files, env examples, README/docs, utility scripts. |
| skipped binary/media | 29 | PDF/PNG/golden fixtures and generated media were not treated as source-reviewed. |

I did not open the real ignored `.env` or `.env.production` files to avoid exposing local secrets. I inspected `.env.example`, `.env.production.example`, compose files, and `.gitignore` instead. `git ls-files` shows only the examples are tracked.

High-confidence clean/implemented areas:

- A1 query/passsage is fixed: `embed_query_text()` exists and `search_service` uses query-side embeddings.
- A2 hybrid merge is fixed: `merge_hybrid_results()` uses RRF, not raw score scale mixing.
- O1/O2/O3/O4 are largely fixed: OCR preprocessing is engine-specific, deskew/DPI/orientation exist, cascade scoring uses quality, failures log/metric.
- O5/O6 are largely fixed: Paddle language/device are configurable and OCR engines are process singletons preloaded from Celery startup.
- PL3/PL4/PL5/PL6 are fixed: plan number parsing, room dimensions, word-boundary plan detection, and non-room filters are covered.
- Frontend F1/F2/F3/F5/F7/F9 are mostly implemented: lazy routes, route role gates, error route, persistent desktop nav, route handle titles, aria labels.

## B) Findings

| ID | Severity | Finding | Evidence | Impact | Remediation |
|---|---|---|---|---|---|
| SEC-01 | Critical | AI aggregate questions bypass tenant scope and price policy. | `backend/app/ai/context.py:285-289`: `result = internal.aggregate_business(db, entity=entity, kind=kind, query=question)`. `backend/app/tools/internal.py:727-754`: `budgets = list(db.scalars(stmt).all())` then returns `total_amount`; `internal.py:772-844` does the same for orders/invoices. | A user can ask chat for totals/counts/top spend across all business rows, not just authorized documents. Users without `can_view_prices` can still receive numeric aggregates because this path runs before any record filtering. | Change `aggregate_business` to accept `AccessScope`, join/filter by allowed `document_id`, and suppress amount/top/amount filters unless `scope.can_view_prices`. Add tests for auditor/operario scopes. |
| SEC-02 | Critical | AI resolved-document payload leaks unredacted amounts after context redaction. | `backend/app/ai/agent.py:251`: `context_items = redact_context_items_for_scope(...)`, but later `agent.py:276-317` builds `resolved_json` from `internal.get_document_full_details`. `backend/app/tools/internal.py:143-160` includes `total_amount`, `unit_price`, `total_price`; `api/routes/ai.py:263` sends `"resolved_document": resolved_json`. | Even when prompt text is redacted, the SSE end event and saved `AIAnswerRead.resolved_document` can expose totals/unit prices to unauthorized users and frontend cards render them. | Add a structured redaction function for resolved-document JSON and apply it before persistence/SSE. Prefer policy-aware payload builders over text regex redaction. |
| SEC-03 | High | REST business endpoints expose monetary fields without applying `can_view_prices`. | `backend/app/services/tenant_access.py:44`: `can_view_prices`. `tenant_access.py:108-125`: operario/auditor default false. `backend/app/schemas/business.py:13`, `:30-31`, `:44`, `:60-61` expose amounts/prices. `backend/app/api/routes/budgets.py:47-60`, `orders.py:36-49`, `invoices.py:15-35` return ORM rows directly after document-scope filtering. | Any user who can see the document can see prices, even if the access policy says prices are hidden. Integration tools implement this redaction, but REST/UI endpoints do not. | Introduce redacted read schemas or response mappers keyed by `scope.can_view_prices`; apply to budgets/orders/invoices/reconciliation/document entity views and frontend types. |
| SEC-04 | High | Reconciliation endpoints ignore tenant scope and price redaction. | `backend/app/api/routes/reconciliation.py:14-16`: returns all `ReconciliationIssue`. `reconciliation.py:23-66`: scans all budgets/orders/invoices and returns all issues. `reconciliation.py:76-80`: updates by ID with no scope check. `backend/app/schemas/professional.py:140-141` expose expected/actual amounts. | Auditor/gestor can list/update issues for documents outside scope and see amounts. Generation creates global issues from all records. | Filter issue rows by accessible document IDs, redact amount fields unless allowed, and scope-check update/generate results. |
| SEC-05 | High | Admin work inbox, counts, and bulk actions are role-only, not document-scope aware. | `backend/app/api/routes/admin_operations.py:183-189`: user dependency is `_`, then global queries. `admin_operations.py:192-323` appends document IDs/titles/action URLs from all docs. `admin_operations.py:328-396` counts all docs/pages/jobs. `admin_operations.py:410-520` retries/reprocesses/marks all matching rows. | Gestor/auditor can see operational metadata for out-of-scope documents; gestor bulk actions can reprocess or mark duplicate documents outside their scope. | Resolve the user scope in all these handlers, filter every query by accessible docs, and scope-check each bulk action target before mutation. |
| SEC-06 | High | Invoice creation can attach financial records to inaccessible documents. | `backend/app/api/routes/invoices.py:38-43`: fetches `Document` and creates `Invoice` without `can_access_document`. | A gestor can create or link invoices against any existing document ID if they can guess it. | Resolve scope and require `can_access_document(db, document, scope)` before creating. Also validate related order scope. |
| SEC-07 | Medium | Watched-file and ingestion-event endpoints leak source paths by role. | `backend/app/api/routes/admin_operations.py:155-180` returns all rows. `backend/app/api/routes/admin_helpers.py:32-45` includes `"path": row.path`; `admin_helpers.py:129-140` includes `"source_path": row.source_path`. | Operational pages can disclose filesystem/source-path structure for inaccessible documents. | Scope-filter by `document_id`; redact paths for unassigned/inaccessible rows. |
| DATA-01 | High | The "no silent hash fallback" policy is still violated in embeddings. | `backend/app/core/config.py:223-230`: default `embedding_provider="local_hash"` and `embedding_fallback_to_hash=True`. `backend/app/services/embeddings.py:366-372`: on provider failure returns `embed_text_hash(...)`. `document_embedding_pipeline.py:61-63` labels the result with the configured provider and `fallback=False` unless provider is `local/local_hash`. `backend/tests/test_document_pipeline.py:289-308` asserts provider failure falls back to hash and labels it `openai_compatible`. | Semantic search can silently degrade to hash vectors while metadata says the real provider was used and chunks do not require reembedding. | Make provider failure raise `EmbeddingProviderError` by default; let `embed_many_with_metadata()` store `embedding=None`, provider `failed`, `needs_reembedding=True`. Remove/rename fallback flag to explicit migration/dev-only mode and fix tests. |
| DATA-02 | Medium | Registration commits before Celery enqueue without an outbox. | `backend/app/services/document_registration_service.py:186`: `db.commit()` persists document/job. `document_registration_service.py:190-196`: `process_document_task.apply_async(...)` happens after commit. `document_registration_service.py:197-214`: queued watched-file state is committed only after enqueue. | If enqueue fails, the document/job remains pending with no queued event. If enqueue succeeds but the second DB commit fails, the worker may process a job whose operational audit state never recorded queued. | Use a transactional outbox or persist `queued` intent before enqueue and have a retrying dispatcher. At minimum catch enqueue failures, mark job failed/needs_retry, and record ingestion event. |
| DATA-03 | Medium | In-memory post-filter pagination causes incomplete pages and wrong totals for scoped users. | `backend/app/api/routes/documents.py:141-145`: loads `max(limit + offset, 500)` then filters/slices. `budgets.py:31-32`, `orders.py:32-33`, `invoices.py:30-35`, `admin_operations.py:103-107` use similar candidate caps. | If many hidden rows precede visible rows, scoped users get short/empty pages and inaccurate totals despite authorized data existing later. | Push access predicates into SQL joins/subqueries or page over authorized IDs. Return exact totals from scoped SQL. |
| FRONT-01 | High | Nested admin routes can crash and still mount every admin query. | `frontend/src/pages/AdminPage.tsx:26-28`: shell calls `useAdminData()`. `AdminPage.tsx:59`: renders `<Outlet />` with no context. Child routes call `useOutletContext<AdminData>()`, e.g. `AdminOperationalRoute.tsx:14`. `useAdminData.tsx:90-120` declares all admin queries in one hook. | `/admin/operativa` and sibling routes can receive `undefined` context and throw at runtime. F4 acceptance is not met: the shell still mounts all admin queries on every admin tab. | Change to `<Outlet context={data} />` immediately, then split `useAdminData` into per-route hooks so each admin sub-route fetches only its own data. |
| FRONT-02 | Medium | Frontend quality gates are broken even though build passes. | `frontend/package.json` uses `eslint ^9.13.0` while repo has `.eslintrc.cjs`; `npm run lint` fails because ESLint 9 expects `eslint.config.js`. `npm test` passes 120 tests but fails global coverage threshold 50%. `npm run format:check` reports 118 files with style drift. | CI cannot reliably protect frontend changes; developers may skip lint/format/test because the default commands fail for tool/config reasons. | Migrate ESLint config to flat config or pin ESLint 8; either raise coverage or lower threshold with per-folder targets; run Prettier once and enforce. |
| OPS-01 | Medium | PDF parser writes JPEG bytes into `.png` preview filenames. | `backend/app/parsers/pdf.py:18-40`: `_render_page_to_jpeg` writes JPEG bytes. `pdf.py:176-178`: `image_file = ... f"page_{page_number}_dpi{dpi}.png"`. `backend/app/api/routes/documents.py:211`: `return FileResponse(path)` lets content type follow extension. | Browsers/proxies may treat JPEG bytes as `image/png`; previews can fail or be cached under the wrong MIME. | Use `.jpg` filenames for JPEG previews or actually render PNG. Set explicit media type when serving. |
| OPS-02 | Medium | Vision/table fallbacks swallow failures without logs/metrics in several paths. | `backend/app/parsers/image.py:90-92`: `except Exception: ... pass`. `backend/app/parsers/pdf.py:497-498`: `except Exception: pass`. `pdf.py:249-303` swallows table extraction failures. | Degraded OCR/table extraction becomes invisible except by missing output. This undercuts operational diagnosis. | Log at debug/warning with document/page context and add counters for vision/table fallback failures. |
| OPS-03 | Medium | Streaming LLM path lacks retry/backoff and non-streaming has a hard-coded outer timeout. | `backend/app/ai/local_client.py:146-194`: `chat_stream()` opens one stream and records failure on any exception. `local_client.py:203-224`: retries exist only in `_post_chat_completion()`. `backend/app/ai/agent.py:393-398`: wraps non-streaming chat in `asyncio.wait_for(..., timeout=60)`. | Intermittent stream setup failures fail immediately; the 60s wrapper can cut off configured retries/backoff (`ai_request_timeout_seconds` defaults 120). | Retry stream connection before first token; remove or configure the 60s wrapper; keep no-replay behavior after tokens have been emitted. |

## C) Cross-Cutting Flow Analyses

### 1. Ingestion -> OCR -> extraction -> indexing

Positive: file security checks signatures/extensions; parser routing handles PDF/images/Office/text; PDF parsing is per-page; OCR cascade has engine-specific preprocess, quality scoring, and DPI ladder; chunks include metadata headers; failed embedding can store unembedded chunks when `EmbeddingProviderError` reaches `document_embedding_pipeline`.

Risks: registration persists jobs before enqueue; multiple best-effort OCR/vision/table failures are invisible; PDF previews have a JPEG/PNG MIME mismatch; embedding fallback can still silently hash vectors before the pipeline can mark chunks as failed.

### 2. Retrieval/RAG/AI answering

Positive: query embeddings use `embed_query_text`; HyDE typo is fixed (`hypothetical`); multi-query reformulation is wired; hybrid search uses RRF; search endpoints add scope keys and filter results after retrieval.

Risks: AI aggregate tools bypass scope entirely; resolved-document payloads are built from unredacted structured entities after text redaction; aggregate amount strings are not reliably caught by regex redaction; cached answers are scoped by access key, but bad payloads can still be cached within that scope.

### 3. Access control and price redaction

Positive: deny-by-default tenant scope exists; access groups can express hotel/chain/document-type/tag/price capabilities; integration tools have explicit price redaction.

Risks: REST business routes, reconciliation, work inbox, ingestion/watched-file views, invoice creation, and AI resolved-document/aggregate paths do not consistently apply the same scope/redaction rules. Price policy is currently fragmented across integration code, AI text regexes, and raw ORM response models.

### 4. Frontend routing/admin/work inbox

Positive: lazy imports and role-gated routes are present; 404/error routes exist; desktop sidebar is persistent; title handling uses route handles; badges have aria labels.

Risks: admin nested routing is broken by missing outlet context and still centralizes all queries; AppShell and Sidebar both subscribe to the `work-inbox-count` query; the dedicated WorkInbox page still polls `/work-inbox?limit=200` every 10s for its content, while the badge count is now separate.

### 5. Ops, deployment, CI, and migrations

Positive: Alembic has a single linear head; frontend production build succeeds and heavy pages are split into chunks; production env example uses Redis auth, secure cookies, deny-by-default tenant access, and hash fallback disabled.

Risks: local/default settings still allow hash fallback; backend focused tests fail on a machine without Tesseract; venv lacks ruff/mypy until dev deps are installed; frontend lint/format/coverage gates fail. The current checked commands are not green enough to claim release readiness.

## D) Test, Lint, Type, Migration Results

Commands run from `C:\Users\PC\Desktop\PROYECTOS\OCR\docu-intel` unless noted:

| Command | Result |
|---|---|
| `python -m pytest --maxfail=20 --disable-warnings` | Failed immediately in global Python due missing backend deps such as `sqlalchemy`, `prometheus_client`, `pandas`. |
| `.venv\Scripts\python.exe -m pytest --maxfail=20 --disable-warnings` | Timed out after ~184s with no usable captured output. |
| `.venv\Scripts\python.exe -m pytest tests/test_embedding_asymmetric_models.py tests/test_ocr_preprocess.py tests/test_ocr_cascade.py tests/test_plan_extraction.py tests/test_search_filters.py tests/test_tenant_access.py --maxfail=5 --disable-warnings -q` | 1 failure: `test_factory_returns_cascading_class_for_cascading_config` fails because local Windows host lacks `tesseract` binary; `app/ocr/tesseract.py:48-50` checks version and raises. |
| `.venv\Scripts\python.exe -m ruff check app` | Failed: `No module named ruff` in venv. |
| `.venv\Scripts\python.exe -m mypy app` | Failed: `No module named mypy` in venv. |
| `python -m ruff check app tests` | Global ruff ran and found 1483 issues, mostly formatting/import/style; not a clean backend lint gate. |
| `npm run build` | Passed. Vite output split heavy pages into chunks, e.g. `ChatPage-*.js`, `PlanoAnnotationPage-*.js`, `DocumentDetailPage-*.js`, `AdminPage-*.js`; initial `index-*.js` still ~435 kB. |
| `npm test -- --runInBand` | Failed because Vitest does not support Jest's `--runInBand`. |
| `npm test` | 16 test files / 120 tests passed, but process exited 1 due global coverage thresholds: lines/statements ~11.2%, functions ~22.47%, threshold 50%. |
| `npm run lint` | Failed before linting: ESLint 9 cannot find `eslint.config.js`; repo uses `.eslintrc.cjs`. |
| `npm run format:check` | Failed: Prettier reports style drift in 118 frontend files. |
| `.venv\Scripts\alembic.exe heads` | `0031_pg_trgm_text_search_indexes (head)`. |
| `.venv\Scripts\alembic.exe history --verbose` | Single linear chain from `0001_initial_schema` to `0031`; numbering skips `0026` but graph is linear. |

## E) Prioritized Remediation Plan

1. **P0: close scope/price leaks.** Make one policy-aware response layer for structured business data and use it in REST, AI resolved documents, aggregates, reconciliation, document entity/detail cards, and frontend types. Add tests for users with `can_view_prices=False`.
2. **P0: scope all operational admin surfaces.** Fix work inbox/list/count/actions, watched files, ingestion events, needs-reembedding, re-embed endpoint, reconciliation update/generate, and invoice create.
3. **P1: remove silent hash fallback.** Default `embedding_fallback_to_hash=False`; make provider failure surface as `EmbeddingProviderError`; store chunks with `embedding=None`, provider `failed`, `needs_reembedding=True`; update tests that currently assert hash fallback.
4. **P1: fix admin nested routes.** Change `AdminPage` to `<Outlet context={data} />` immediately, then split `useAdminData` into per-tab hooks and add a route render test for `/admin/operativa`.
5. **P1: push access filtering into SQL.** Replace candidate-cap post-filtering in documents/business/admin lists with scoped SQL predicates or authorized-ID subqueries.
6. **P2: harden queue state.** Add a durable outbox/dispatcher or retryable enqueue state so a committed document/job cannot be stranded before Celery receives it.
7. **P2: make fallback degradation observable.** Log/metric vision, pdfplumber, OCR page reprocess, and table extraction failures with page/document context.
8. **P2: repair quality gates.** Install backend dev deps in venv/CI; decide on Ruff baseline; migrate ESLint config or pin ESLint 8; run Prettier; adjust frontend coverage policy.
9. **P3: fix preview MIME consistency.** Store rendered JPEGs as `.jpg` or render true PNG; set explicit `media_type`.
10. **P3: align LLM retry behavior.** Add stream setup retries before first token and make the outer non-streaming timeout configurable.

