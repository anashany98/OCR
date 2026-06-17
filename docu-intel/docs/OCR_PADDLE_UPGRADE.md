# OCR Upgrade: PaddleOCR 3.7 / PP-OCRv6 / PaddleX 3.7.1 / PP-StructureV3

> Audience: backend operators who maintain Docu-Intel. Status: shipped on
> branch `upgrade-paddleocr-3-7-ppocrv6-structurev3-future-proof` (merge
> target: `master`).

This document explains the **what**, **why** and **how** of the PaddleOCR
3.7 / PP-OCRv6 / PaddleX 3.7.1 / PP-StructureV3 upgrade. Pair it with
[`OCR_VERSIONING_AND_UPGRADES.md`](./OCR_VERSIONING_AND_UPGRADES.md) for
the long-term forward-compatibility story (how to add PP-OCRv7, how to
add a new PP-StructureV4, etc.).

---

## 1. What changed

| Component | Before | After |
|---|---|---|
| PaddleOCR | 3.5.0 | **3.7.0** (PP-OCRv6 server / mobile / tiny / small / medium) |
| PaddleX (PP-Structure / layout_parsing) | 3.5.2 | **3.7.1** (PP-StructureV3 + layout_parsing legacy) |
| Architecture | Engines talk to PaddleOCR / PaddleX directly | **Adapters** (`paddle_adapter.py`, `structure_adapter.py`) hide version drift; **registry** (`model_registry.py`) centralises profile selection |
| Profile selection | Hardcoded model names in `paddle.py` / `pp_structure.py` | `PADDLE_OCR_PROFILE` / `PP_STRUCTURE_PROFILE` settings + `model_registry.py` |
| Output normalisation | Inline in `paddle.py` (≈ 50 lines of format-detection) | Centralised in `normalize_paddle_output()` / `normalize_structure_output()` |
| Predict vs legacy `ocr()` API | Hardcoded `ocr()` | Adapter prefers `predict()` when available, falls back to `ocr()`, honours `PADDLE_FORCE_LEGACY_OCR_API` / `PADDLE_FORCE_PREDICT_API` |
| Future PP-OCRv7 / PP-StructureV4 | Would require touching engine code + tests + cascading | Add a profile to `model_registry.py` and (if shape changes) extend `normalize_*_output` |

The Tesseract Tier 1 cascade path is **unchanged** — the upgrade does
not touch `tesseract.py` or the cascading engine's quality scoring.

---

## 2. Why we did it

* PaddleOCR 3.5.0 + PaddleX 3.5.2 are the latest versions that still
  ship the pre-`predict()` API. Newer versions (3.6+) start dropping the
  legacy `ocr()` method and changing how confidence scores are
  reported. **The 3.5.x line is the legacy API; 3.7.x is the modern
  API.** Sticking with 3.5 forever would have meant owning the legacy
  shape forever.
* PP-OCRv6 (server / mobile / tiny / small / medium) ships with
  PaddleOCR 3.7.0 and is the first profile family that:
  * Reports structured `rec_texts / rec_scores / dt_polys` directly
    through `predict()` (no more parsing nested lists).
  * Supports the new `use_textline_orientation` setting (which replaces
    the deprecated `use_angle_cls`).
* PP-StructureV3 ships with PaddleX 3.7.1 and improves layout detection
  accuracy on invoices / planos / receipts. PP-StructureV3 also returns
  a cleaner `parsing_res_list` payload than V2.
* The previous architecture coupled engines to Paddle versions. Every
  upgrade forced us to edit `paddle.py` / `pp_structure.py` and the
  cascading fallback logic. The new adapter + registry split means the
  next upgrade is a settings flip, not a code change.

---

## 3. What's new in the codebase

### 3.1 New modules

```
app/ocr/
├── model_registry.py        # Pure-data profile catalogue (no Paddle import)
├── paddle_adapter.py         # PaddleOCR compatibility adapter (predict / ocr / output norm)
├── structure_adapter.py      # PP-Structure / PaddleX compatibility adapter (V3 / fallback / output norm)
└── adapter.py                # Re-exports the two adapters + helpers
```

`app/ocr/paddle.py` and `app/ocr/pp_structure.py` are now thin
delegates that own the legacy engine surface (`name`, `extract`,
`_engine`, `_pipeline`) but route every call through the adapter.

### 3.2 New settings

See [`OCR_VERSIONING_AND_UPGRADES.md`](./OCR_VERSIONING_AND_UPGRADES.md#settings)
for the full table. The short version:

```env
PADDLE_OCR_PROFILE=ppocr_v6_medium
PADDLE_USE_PREDICT_API=true
PP_STRUCTURE_PROFILE=pp_structure_v3
OCR_CASCADING_USE_PP_STRUCTURE=false
```

### 3.3 Tests

| Test file | Covers |
|---|---|
| `tests/test_model_registry.py` | Profile catalogue, unknown-id fallback, ENV overrides |
| `tests/test_paddle_adapter.py` | predict vs ocr routing, output normalisation, lazy init, runtime info |
| `tests/test_structure_adapter.py` | V3 vs fallback, GPU refusal, markdown export, output normalisation |
| `tests/test_paddleocr_output_formats.py` | Predict dict, legacy nested list, object-style, generator, strict mode |
| `tests/test_predict_ocr_fallback.py` | predict preferred, fallback to ocr on failure / missing, no-API engines |
| `tests/test_future_compatibility.py` | New top-level shapes, new keys, unknown payloads |

All tests run without PaddleOCR / PaddleX installed — the adapters
accept an `engine_factory` callable so unit tests inject a mock.

---

## 4. How to roll it out

### 4.1 Development environment (no GPU)

```bash
cd docu-intel/backend
pip install -r requirements.txt    # installs paddleocr==3.7.0
pip install paddlepaddle==3.3.1    # CPU-only wheel
```

`paddlex[ocr]==3.7.1` is **GPU-only** in this release (PaddlePaddle 3.x
PIR executor crashes `layout_parsing` on CPU). The CPU image does NOT
install `paddlex[ocr]` — the cascade will refuse to instantiate Tier 3
on CPU and degrade to Tier 1 + Tier 2 only. This is by design.

### 4.2 GPU environment (RTX 4070)

The GPU image (`Dockerfile.gpu`) installs:

```bash
paddlepaddle-gpu==3.3.1   # from paddlepaddle.org.cn CUDA 12.6 index
paddlex[ocr]==3.7.1       # PP-StructureV3 + layout_parsing
```

Build & run with the existing `docker compose --env-file .env.production
-f docker-compose.prod.yml up -d --build` workflow.

### 4.3 Smoke test

```bash
cd docu-intel/backend
python -c "from app.ocr.paddle_adapter import PaddleOCRAdapter; \
           print(PaddleOCRAdapter.__doc__[:200])"
```

Then run the unit suite (no GPU required):

```bash
python -m pytest tests/test_model_registry.py tests/test_paddle_adapter.py \
                  tests/test_structure_adapter.py \
                  tests/test_paddleocr_output_formats.py \
                  tests/test_predict_ocr_fallback.py \
                  tests/test_future_compatibility.py
```

All 86 tests pass with no PaddleOCR / PaddleX import.

### 4.4 Benchmark against golden fixtures

```bash
python scripts/benchmark_paddleocr_upgrade.py \
    --input-dir /app/data/test_ocr \
    --limit 50 \
    --output-json /app/data/ocr_benchmark_results.json \
    --engine cascading \
    --verbose
```

The script:

* Renders each PDF / image in the input dir.
* Runs the requested engine (default: cascading) against every page.
* Emits a per-page table on stdout.
* Emits a JSON report with `paddleocr_version`, `paddleocr_profile`,
  `paddlex_version`, `structure_profile`, `pages_succeeded`,
  `mean_confidence`, `p50/p95 duration`.
* Falls back to Tesseract-only when PaddleOCR is unavailable so the
  script never crashes just because the operator forgot to install it.

---

## 5. How to disable / rollback

The upgrade is designed to be **additive and reversible**:

* Set `OCR_ENGINE=tesseract` in `.env.production` to bypass the cascade
  and run Tier 1 only.
* Set `OCR_CASCADING_USE_PP_STRUCTURE=false` to skip Tier 3 even when
  the cascade is on.
* Set `PADDLE_FORCE_LEGACY_OCR_API=true` to force the legacy `ocr()`
  API path on the adapter (useful if a future PaddleOCR build breaks
  `predict()`).
* Set `PP_STRUCTURE_FORCE_PADDLEX_FALLBACK=true` to disable
  `PPStructureV3` and use the legacy `paddlex.create_pipeline(
  "layout_parsing")` path.
* Revert the upgrade commit-by-commit (each `UPG-N` is independent):
  `git revert <hash>..<hash>` brings the codebase back to the previous
  pinned versions.

---

## 6. Risks

* **PaddleOCR 3.7.0 model download.** First call downloads ~150-300 MB
  of model weights per profile. The adapter's init timeout (120 s) is
  generous; if the worker cannot download within that window the
  adapter raises `RuntimeError` and the cascade keeps the primary
  (Tesseract) result.
* **PaddleX dependency overhead.** `paddlex[ocr]` pulls a few hundred
  MB of additional Python packages. The CPU image does NOT install
  it; the GPU image does. If the operator needs PP-Structure on CPU
  they must migrate to the GPU image.
* **PP-Structure output shape drift.** PaddleX has shipped at least
  three different payload shapes over the years. The
  `normalize_structure_output()` function accepts every known shape
  and returns the canonical `OCRBlock` list. A future PaddleX that
  introduces a fourth shape will require extending the normaliser.
  The future-compatibility tests pin the contract.
* **No PaddleOCR-VL.** This upgrade does NOT introduce PaddleOCR-VL.
  That stays out of scope until the operator explicitly opts in via a
  future `O7` task.

---

## 7. What the operator needs to do today

1. Merge the branch into `master`.
2. Rebuild the GPU image (`docker compose build worker-heavy`).
3. Restart the workers.
4. Tail `app.ocr.paddle_adapter` / `app.ocr.structure_adapter` log
   lines on first run — each engine emits a one-shot INFO line with
   profile + version + device.
5. Run the benchmark script against the golden fixtures (the project
   ships fixtures in `data/test_ocr/` if present; otherwise point it
   at any directory with scanned PDFs).
6. If the upgrade looks bad, flip the rollback flags in
   `.env.production` (see §5) and rebuild — no code revert needed.