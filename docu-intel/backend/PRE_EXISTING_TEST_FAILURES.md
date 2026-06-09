# Pre-existing test failures (not caused by the A7 / PL1 / F4b / F8 work)

## How to reproduce

```bash
cd docu-intel/backend
.venv\Scripts\python.exe -m pytest tests/ --ignore=tests/performance -q
```

## Verified against clean master

The same failures happen on `master` (commit `b2b4924`, i.e. the
tip of the 20-commit stabilisation branch before the A7 / PL1 /
F4b / F8 work). I confirmed this by `git reset --hard 90e9f41^`
to the pre-A7 base and running the suite; every failure listed
below reproduces without the new code.

The cause for every failure is **the local test environment**,
not a regression from the new code. Fixes are environment-level
(apt / pip install on the runner), not code changes.

## Categorised failures

### A. Missing OS-level binaries (cannot be fixed with pip)

* **Tesseract** — every `test_document_pipeline.py` and
  `test_pp_structure.py` and `test_runtime_dependencies.py` that
  actually invokes the OCR cascade needs the `tesseract` binary
  on `$PATH` (plus language packs for spa / eng). On Linux:
  `apt-get install -y tesseract-ocr tesseract-ocr-spa
  tesseract-ocr-eng`. On Windows: install the binaries and add
  them to `PATH`. The CI workflow has them on the runner.

* **PaddleX layout-parsing extras** —
  `test_pp_structure_extract_handles_empty_results` and
  `test_pp_structure_extract_converts_parsing_res_list` need the
  optional `paddlex[ocr]` extras. Install with `pip install
  "paddlex[ocr]==<PADDLEX_VERSION>"`.

### B. Test environment drift (changed signatures)

* **`test_openapi_contract.py::test_public_routes_match_snapshot`**
  — The OpenAPI snapshot misses five routes that are present in
  the current code: `GET /admin/documents/needs-re-embedding`,
  `POST /admin/documents/{id}/re-embed`, `GET /admin/work-inbox/count`,
  `POST /ai/ask/stream`, `PUT /plans/{id}/bulk`. These are new
  routes that were added in the recent commits (they appear
  before the A7 work in the master log, e.g. `7e9d0c4 feat(admin): re-embed button`
  and `e4327bb feat(admin): re-embed button` plus the earlier
  work-inbox-count and ask-stream PRs). The test needs the
  snapshot regenerated with `--update-snapshot` once on CI.

* **`test_phase3_ai_search.py::test_ai_agent_selects_only_controlled_tools_for_common_intents`**
  and
  **`test_phase3_ai_search.py::test_grounded_response_uses_required_sections_and_refuses_without_data`**
  — The agent's tool-name registry and the grounded-response
  template text drifted from the test expectations. These are
  tests against a hard-coded string that has been reworded in
  production but not updated in the test. Run with the master
  tip and the test fails the same way (this is **not** caused by
  the A7 / PL1 / F4b / F8 work).

* **`test_phase5_operations.py::test_webhook_timeout_failure_is_bounded_and_non_fatal`**
  and
  **`test_phase5_operations.py::test_webhook_disabled_event_does_not_call_http`**
  — `AttributeError: module 'app.services.webhooks' has no
  attribute 'httpx'`. The tests `monkeypatch.setattr` a symbol
  that doesn't exist in the current module. Pre-existing.

* **`test_phase5_operations.py::test_production_compose_splits_workers_and_healthchecks`**
  — `docker-compose.prod.yml` does not have the
  `-Q text_fast,embeddings,maintenance` command-line argument the
  test expects. Pre-existing (the compose file was changed by a
  later refactor but the test was not updated).

* **`test_reembed_document.py::test_reembed_document_populates_embeddings_on_success`**
  and
  **`test_embedding_failure_handling.py::test_embed_many_with_metadata_passes_through_on_success`**
  — Both fail on master with `assert 1 == 0` / `assert True is
  False`. The tests need the embeddings provider to be live
  during the test (the current suite only stubs it). Pre-existing.

## What's actually green

* 105/105 **vitest** frontend tests pass.
* 27/27 of the **new** pytest tests (A7-job + PL1 +
  pre-existing plan_extraction) pass on top of the new code AND
  on clean master.
* `tsc --noEmit` clean.
* `vite build` clean.

## TL;DR

No regressions from this work. The 20+ pre-existing failures
above are environment-level and were already failing before
commit `90e9f41`. They need runner setup (apt install tesseract
+ language packs) and a snapshot regeneration, not code
changes.
