# Hyper-Extract — Optional Structured-Extraction Layer

Hyper-Extract is an **optional** module that runs **after** the OCR pipeline has
produced clean text and turns it into a structured JSON payload
(`fields`, `entities`, `relations`) using a configurable LLM
(OpenAI-compatible — MiniMax M3, OpenAI, LM Studio, vLLM, Ollama…).

It does **not** replace OCR. The OCR pipeline is the source of truth; Hyper-Extract
is an additive enrichment layer that fails-soft so a provider outage never
breaks document processing.

> **Status (this branch):** initial integration. Feature-flagged, off by
> default, no production traffic. See "Limitaciones conocidas" at the
> bottom before turning it on.

---

## 1. What it does

```
PDF / image
   │
   ▼
OCR pipeline (Tesseract → PaddleOCR → PP-Structure)
   │
   ▼
Clean OCR text + document metadata
   │
   ▼
┌──────────────────────────────────────────────────────────┐
│  Hyper-Extract (this module, OFF by default)            │
│  ─────────────────────────────────────────────────────   │
│  1. pick a template (factura / albaran / contrato /     │
│     presupuesto) by document_type                       │
│  2. build a system+user prompt with the template's      │
│     field list                                           │
│  3. POST to the OpenAI-compatible chat-completions      │
│     endpoint                                              │
│  4. parse the JSON response (fenced / balanced / raw)   │
│  5. persist into `document_extractions`                  │
└──────────────────────────────────────────────────────────┘
   │
   ▼
Structured JSON / API / Review Panel
```

## 2. What it does NOT do

* It does **not** re-run OCR. It consumes the OCR text that the
  pipeline already produced.
* It does **not** mutate the existing OCR response (the
  `document.upload` response shape is unchanged).
* It does **not** block the OCR pipeline. Any failure is contained in
  `app/services/hyperextract/service.py`; the OCR / business extraction /
  embeddings all keep their existing behaviour.
* It does **not** call the provider when `HYPEREXTRACT_ENABLED=false`.
* It does **not** log API keys, full request bodies or the URL of the
  provider (no token / URL leak in the error envelope).

## 3. Variables de entorno

Add these to `.env` (or your deployment secret manager). Defaults are
safe — the module stays inert.

```dotenv
# Master switch. MUST be true for any provider call.
HYPEREXTRACT_ENABLED=false

# OpenAI-compatible provider (LM Studio, vLLM, Ollama /v1, OpenAI, MiniMax M3).
HYPEREXTRACT_PROVIDER=openai_compatible
HYPEREXTRACT_BASE_URL=
HYPEREXTRACT_MODEL=
HYPEREXTRACT_API_KEY=
HYPEREXTRACT_TIMEOUT_SECONDS=120
HYPEREXTRACT_MAX_RETRIES=1

# Storage for raw payloads (audit / replay). The DB row also keeps a
# truncated copy when HYPEREXTRACT_PERSIST_RAW_OUTPUT=true.
HYPEREXTRACT_OUTPUT_DIR=./storage/hyperextract

# Document type to assume when the caller does not specify one.
HYPEREXTRACT_DEFAULT_TYPE=factura
HYPEREXTRACT_PERSIST_RAW_OUTPUT=true

# When true, Hyper-Extract runs automatically inside the OCR pipeline.
# When false (default), only the API or the test script trigger it.
HYPEREXTRACT_RUN_IN_PIPELINE=false
```

### Connecting MiniMax M3 (OpenAI-compatible)

The repository exposes `MINIMAX_*` variables so the operator can wire a
MiniMax-M3 gateway without touching the code:

```dotenv
HYPEREXTRACT_ENABLED=true
HYPEREXTRACT_PROVIDER=openai_compatible
HYPEREXTRACT_BASE_URL=https://api.minimax.io/v1
HYPEREXTRACT_MODEL=MiniMax-M3
HYPEREXTRACT_API_KEY=<your key>
```

The values in `MINIMAX_BASE_URL` / `MINIMAX_MODEL` are placeholders for
documentation; copy them into `HYPEREXTRACT_*` to actually use the
gateway.

## 4. How to activate it

### Step 1 — apply the migration

```bash
cd docu-intel/backend
alembic upgrade head
```

That creates the `document_extractions` table (migration
`0036_document_hyperextract.py`). The migration is non-destructive:
installations that never enable the feature just keep an empty table.

### Step 2 — configure the provider

Edit `.env`:

```dotenv
HYPEREXTRACT_ENABLED=true
HYPEREXTRACT_BASE_URL=https://api.minimax.io/v1
HYPEREXTRACT_MODEL=MiniMax-M3
HYPEREXTRACT_API_KEY=<set me>
HYPEREXTRACT_RUN_IN_PIPELINE=false   # start with manual mode
```

### Step 3 — restart the backend

```bash
docker compose restart backend
```

### Step 4 — health probe

```bash
curl -s http://localhost:8000/api/v1/documents/hyperextract/status \
     -H "Authorization: Bearer <jwt>"
```

Returns:

```json
{
  "enabled": true,
  "provider": "openai_compatible",
  "model": "MiniMax-M3",
  "base_url_configured": true,
  "timeout_seconds": 120,
  "run_in_pipeline": false,
  "default_type": "factura",
  "templates": ["albaran", "contrato", "factura", "presupuesto"],
  "checked_at": "2026-06-26T11:09:03.123Z"
}
```

### Step 5 — flip `RUN_IN_PIPELINE` when ready

Set `HYPEREXTRACT_RUN_IN_PIPELINE=true` to call Hyper-Extract
automatically for every processed document. Until then the API
(`POST /documents/{id}/extract`) and the test script are the only
triggers.

## 5. How to test it

### CLI smoke test (no DB)

```bash
cd docu-intel/backend
python scripts/test_hyperextract.py \
    --file ./samples/factura_ocr.txt \
    --type factura
```

With environment overrides:

```bash
HYPEREXTRACT_ENABLED=true \
HYPEREXTRACT_BASE_URL=https://api.minimax.io/v1 \
HYPEREXTRACT_MODEL=MiniMax-M3 \
HYPEREXTRACT_API_KEY=$YOUR_KEY \
python scripts/test_hyperextract.py --text "FACTURA 2026-001 ..." --type factura
```

Exit codes:
* `0` → success / disabled (nothing to do)
* `2` → provider returned a failure (`status="failed"`)
* `1` → bad CLI args

### API

```bash
# Run an extraction against an already-processed document.
curl -X POST http://localhost:8000/api/v1/documents/42/extract \
     -H "Authorization: Bearer <jwt>" \
     -H "Content-Type: application/json" \
     -d '{"document_type": "factura"}'

# Force a run even when the feature flag is off (admin-only).
curl -X POST http://localhost:8000/api/v1/documents/42/extract/retry \
     -H "Authorization: Bearer <jwt>" \
     -H "Content-Type: application/json" \
     -d '{"document_type": "factura", "force": true}'

# Read the latest persisted result.
curl http://localhost:8000/api/v1/documents/42/extraction \
     -H "Authorization: Bearer <jwt>"
```

All endpoints require `admin` or `gestor`; the dedicated status probe
(`GET /documents/hyperextract/status`) only requires authentication.

## 6. Output envelope

The service always returns the same shape regardless of status:

```json
{
  "enabled": true,
  "status": "success",
  "document_id": 42,
  "document_type": "factura",
  "fields": {
    "proveedor": "ACME S.L.",
    "cif_nif": "B12345678",
    "numero_factura": "2026-001",
    "fecha": "2026-06-01",
    "base_imponible": 1000.0,
    "iva": 210.0,
    "total": 1210.0,
    "moneda": "EUR"
  },
  "entities": [],
  "relations": [],
  "raw_output": {"_raw": "<first 4 KB of provider text>"},
  "warnings": [],
  "provider": "openai_compatible",
  "model": "MiniMax-M3",
  "latency_ms": 1834
}
```

Status values:
* `disabled` — `HYPEREXTRACT_ENABLED=false`. No provider call.
* `success` — extraction ran, fields populated.
* `failed` — provider error or invalid JSON. `error_message` carries a
  short reason (no token, no URL, no body).
* `skipped` — invoked but no OCR text was available.
* `pending` — internal status; surfaces when the row was created but
  not yet populated by the service.

## 7. Plantillas (templates)

Templates live in `backend/app/services/hyperextract/templates/*.yaml`.
Each file:

* Lists the fields the model should populate (type + description +
  optional `required`).
* Provides a Spanish `system_prompt` that primes the model for the
  document type.
* Declares the entity types and relation types the reviewer should see.

Shipped templates:

| document_type | file                              |
|---------------|-----------------------------------|
| `factura`     | `factura.yaml`                    |
| `albaran`     | `albaran.yaml`                    |
| `contrato`    | `contrato.yaml`                   |
| `presupuesto` | `presupuesto.yaml`                |

To add a new template, drop another `*.yaml` in the directory and call
`app.services.hyperextract.templates.reset_cache()` (or restart the
worker). The service picks it up on the next call.

## 8. Persistence

Every run (except `disabled`) writes one row to `document_extractions`:

| column            | description                                              |
|-------------------|----------------------------------------------------------|
| `document_id`     | FK to `documents.id` (cascade delete).                   |
| `document_type`   | The template used (or `null` if no template matched).    |
| `provider` / `model` | The configured provider name and model name.         |
| `status`          | `success` / `failed` / `pending` / `skipped`.            |
| `fields_json`     | The extracted `fields` map.                              |
| `entities_json`   | The extracted `entities` list.                           |
| `relations_json`  | The extracted `relations` list.                          |
| `warnings_json`   | Anything the model flagged as unreliable.                |
| `raw_output_json` | First 4 KB of the provider response (audit / replay).    |
| `error_message`   | Short, sanitised reason on `failed`.                     |
| `latency_ms`      | Wall-clock latency of the provider call.                 |
| `created_at` / `updated_at` | Standard timestamps.                           |

## 9. Endpoints

| method | path                                            | role          | description                                   |
|--------|-------------------------------------------------|---------------|-----------------------------------------------|
| POST   | `/api/v1/documents/{id}/extract`                | admin / gestor| Run extraction on the document's OCR text.    |
| POST   | `/api/v1/documents/{id}/extract/retry`          | admin / gestor| Same as above (explicit retry, audit-friendly).|
| GET    | `/api/v1/documents/{id}/extraction`             | admin / gestor| Latest persisted result (or `null`).          |
| GET    | `/api/v1/documents/{id}/extractions`            | admin / gestor| History, newest first.                        |
| GET    | `/api/v1/documents/hyperextract/status`         | any logged in  | Lightweight health probe.                     |

## 10. Limitaciones conocidas

* **No real provider call in CI.** The smoke test exits with
  `status="disabled"` by default. To exercise the network path you
  need a real provider (or a local LM Studio / vLLM).
* **Templates are minimal.** They define field names and a system
  prompt, not a deterministic parser. Numeric / date fields still rely
  on the LLM extracting them correctly. The deterministic
  `business_extraction` regex layer keeps doing the heavy lifting for
  production invoices / orders / budgets; Hyper-Extract is the
  **enrichment**.
* **Single provider at a time.** Per-document `provider` / `model`
  override is not exposed yet (planned in the API).
* **No streaming.** Latency is bounded by `HYPEREXTRACT_TIMEOUT_SECONDS`
  (default 120 s). Long documents are truncated at 32 k characters in
  the user prompt — operators that need more should chunk upstream.
* **No retry/backoff inside the service.** The pipeline integration
  relies on the existing Celery retry policy. The HTTP client raises on
  the first failure; an operator can wrap the call in a Celery task
  later.
* **No webhooks.** A successful extraction does not yet emit a
  `document.extracted` event. Adding it is a one-file change in
  `app.services.webhooks`.
* **No review UI.** The persisted rows are queryable via
  `GET /documents/{id}/extractions`; the admin panel is not wired yet.

## 11. Próximos pasos

1. Front-end admin tab that lists `document_extractions` and lets the
   operator mark fields as `needs_review`.
2. Celery task for scheduled batch re-extraction of documents whose
   provider became available after the fact.
3. Per-document `provider` / `model` override via the API.
4. Emit `document.extracted` webhook event for downstream consumers.
5. Confidence calibration: parse the model's confidence / `usage`
   fields and persist them into `confidence` / `latency_ms` for
   monitoring.
6. Integration tests with a deterministic mock provider so the CI can
   exercise the full envelope shape without paying for tokens.

## 12. Files added / modified

See the branch `feature/hyper-extract-integration` for the full diff.
Headline:

* **Added**
  * `backend/app/services/hyperextract/__init__.py`
  * `backend/app/services/hyperextract/service.py`
  * `backend/app/services/hyperextract/templates.py`
  * `backend/app/services/hyperextract/templates/{factura,albaran,contrato,presupuesto}.yaml`
  * `backend/app/models/hyperextract.py`
  * `backend/app/schemas/hyperextract.py`
  * `backend/app/api/routes/hyperextract.py`
  * `backend/alembic/versions/0036_document_hyperextract.py`
  * `backend/scripts/test_hyperextract.py`
  * `docs/hyperextract.md` (this file)
* **Modified**
  * `backend/app/core/config.py` (new `hyperextract_*` settings)
  * `backend/app/models/__init__.py` (export `DocumentExtraction`)
  * `backend/app/models/document.py` (`Document.extractions` relationship)
  * `backend/app/api/router.py` (mount the new router under `/documents`)
  * `backend/app/services/document_processing_core.py` (optional
    `_maybe_run_hyperextract` call after `_apply_classification_and_extraction`)
  * `.env.example` (new variables, including the MiniMax M3 placeholder block)