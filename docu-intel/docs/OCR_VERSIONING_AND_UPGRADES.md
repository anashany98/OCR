# OCR Versioning & Upgrade Policy (future-proof)

> Audience: backend operators who maintain Docu-Intel. Status: shipped on
> branch `upgrade-paddleocr-3-7-ppocrv6-structurev3-future-proof` (merge
> target: `master`).

This document describes the **long-term** OCR versioning story: how to
add a new PaddleOCR / PP-OCR profile family (e.g. PP-OCRv7), how to add
a new PP-Structure version (e.g. V4), and how to detect / react to a
new PaddleOCR output shape without breaking the cascade. Pair it with
[`OCR_PADDLE_UPGRADE.md`](./OCR_PADDLE_UPGRADE.md) for the immediate
upgrade context.

---

## 1. The adapters / registry pattern

The codebase deliberately splits OCR into three layers:

```
┌──────────────────────────────────────────────────────────────────┐
│  Setting (PADDLE_OCR_PROFILE, PP_STRUCTURE_PROFILE, …)           │
└─────────────────────────────┬────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│  app/ocr/model_registry.py                                       │
│  Pure data. Maps a profile id → OcrProfile / StructureProfile.   │
│  No PaddleOCR / PaddleX import. No model download.               │
└─────────────────────────────┬────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│  app/ocr/paddle_adapter.py / structure_adapter.py                │
│  Owns the PaddleOCR / PaddleX constructor call. Owns the         │
│  predict-vs-ocr routing. Owns the output normalisation.         │
└─────────────────────────────┬────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│  app/ocr/paddle.py / pp_structure.py (engine surface)            │
│  Thin delegate. Keeps BaseOCREngine contract. Delegates to the   │
│  adapter.                                                        │
└──────────────────────────────────────────────────────────────────┘
```

The rule: **only `*_adapter.py` talks to PaddleOCR / PaddleX**. The
engines and the cascade never import `paddleocr` or `paddlex`
directly. This is the seam that lets a future PaddleOCR upgrade land
without touching engine code.

---

## 2. Settings reference

All knobs live in `app.core.config.Settings`. Read the table below and
flip the flags via `.env` / `.env.production`. None of them require a
code change.

### 2.1 PaddleOCR settings

| Setting | Default | Purpose |
|---|---|---|
| `paddle_ocr_profile` | `ppocr_v6_medium` | Profile id resolved via `model_registry.get_ocr_profile`. Unknown ids fall back to the default with a WARNING. |
| `paddle_text_detection_model_name` | `None` | Detection model override (uses profile default when empty). |
| `paddle_text_recognition_model_name` | `None` | Recognition model override. |
| `paddle_use_predict_api` | `True` | Prefer PaddleOCR 3.x `predict()` over legacy `ocr()`. |
| `paddle_force_legacy_ocr_api` | `False` | Force the legacy `ocr()` path even when `predict` is available. |
| `paddle_force_predict_api` | `False` | Force `predict()` even when `use_predict_api=False`. |
| `paddle_allow_unknown_output_format` | `True` | Silently swallow unknown output shapes (recommended). |
| `paddle_log_runtime_info` | `True` | Emit one-shot INFO log with version + profile + device. |

### 2.2 PP-Structure / PaddleX settings

| Setting | Default | Purpose |
|---|---|---|
| `pp_structure_profile` | `pp_structure_v3` | Profile id resolved via `model_registry.get_structure_profile`. |
| `pp_structure_pipeline_name` | `None` | Pipeline name override (only honoured by `custom` profile). |
| `pp_structure_use_v3` | `True` | Try `PPStructureV3` first; fall back to `paddlex.create_pipeline`. |
| `pp_structure_export_markdown` | `True` | Append markdown export to `OCRResult.text` when the version exposes one. |
| `pp_structure_export_json` | `True` | Persist raw structured JSON on the result metadata. |
| `pp_structure_force_paddlex_fallback` | `False` | Force legacy `paddlex.create_pipeline('layout_parsing')`. |
| `pp_structure_log_runtime_info` | `True` | Emit one-shot INFO log on init. |

### 2.3 Cascade settings (unchanged by the upgrade)

| Setting | Default | Purpose |
|---|---|---|
| `ocr_engine` | `cascading` | Top-level engine selector: `tesseract` / `paddleocr` / `cascading` / `pp_structure`. |
| `ocr_cascading_use_pp_structure` | `False` | Master switch for Tier 3. Off by default — Tier 3 is GPU-only and adds ~500 MB model download. |
| `ocr_cascading_min_chars` | `30` | Min characters for the primary to be acceptable. |
| `ocr_cascading_min_confidence` | `0.5` | Min confidence for the primary to be acceptable. |

---

## 3. Adding a new PaddleOCR profile (PP-OCRv7 example)

Suppose PaddleOCR 4.0 ships PP-OCRv7 profiles (`ppocr_v7_tiny`,
`ppocr_v7_small`, `ppocr_v7_medium`, `ppocr_v7_server`). To onboard them:

1. Add the profiles to `app/ocr/model_registry.py`:

   ```python
   _OCR_PROFILES["ppocr_v7_tiny"] = OcrProfile(
       id="ppocr_v7_tiny",
       backend="paddleocr",
       model_type="PP-OCRv7",
       detection_model_name=None,
       recognition_model_name=None,
       use_predict_api=True,
       description="PP-OCRv7 tiny profile (PP-OCRv7 baseline).",
   )
   # … repeat for the other v7 profiles
   ```

2. Bump `paddleocr==4.0.0` in `requirements.txt` and rebuild the image.

3. (If the output shape changed) extend
   `app/ocr/paddle_adapter.normalize_paddle_output()` to recognise the
   new shape. The function is structured as a series of `isinstance`
   checks that you can append to without breaking the existing ones.

4. Add a test case to `tests/test_paddleocr_output_formats.py` that
   pins the new shape. Run the suite; if the new test fails the
   adapter is incomplete.

5. Flip `PADDLE_OCR_PROFILE=ppocr_v7_medium` in `.env.production`. No
   code change is needed for the engines or the cascade.

6. Run the benchmark script (`scripts/benchmark_paddleocr_upgrade.py`)
   against the golden fixtures. Compare the new profile's
   `mean_confidence` and `p95 duration` against the old one. If the
   new profile is worse, the rollback is one flag flip back to
   `ppocr_v6_medium`.

The whole onboarding is ~30 lines of data + ~30 lines of test. No
engine code, no cascading code, no parser code.

---

## 4. Adding a new PP-Structure version (V4 example)

The same pattern applies to `pp_structure_profile`. Suppose PaddleX
4.0 ships PP-StructureV4:

1. Add the profile to `app/ocr/model_registry.py`:

   ```python
   _STRUCTURE_PROFILES["pp_structure_v4"] = StructureProfile(
       id="pp_structure_v4",
       backend="paddlex",
       pipeline="layout_parsing",
       prefer_v4=True,
       description="PP-StructureV4 via PPStructureV4 when available.",
   )
   ```

2. Extend `_STRUCTURE_PROFILES` default list and bump the
   `_DEFAULT_STRUCTURE_PROFILE_ID` if V4 should be the default.

3. Extend `app/ocr/structure_adapter.StructureAdapter._default_init`
   to try `PPStructureV4` first:

   ```python
   if self.profile.prefer_v4:
       try:
           from paddlex import PPStructureV4  # type: ignore[attr-defined]
           instance = PPStructureV4(device=self.device)
           return instance
       except Exception as exc:
           logger.warning("PPStructureV4 unavailable; falling back to V3")
   # … existing V3 + paddlex.create_pipeline fallback chain
   ```

4. (If the output shape changed) extend
   `app/ocr/structure_adapter.normalize_structure_output()` to
   recognise the new payload.

5. Flip `PP_STRUCTURE_PROFILE=pp_structure_v4` in `.env.production`.
   No other code change required.

---

## 5. Detecting a new PaddleOCR output shape

The adapter is intentionally tolerant. When PaddleOCR ships a new
shape:

1. The default `paddle_allow_unknown_output_format=True` makes the
   adapter return an empty `OCRResult` instead of raising. The cascade
   will keep the primary (Tesseract) result and the admin UI will show
   a row of "PaddleOCR returned no blocks".

2. The operator will see a `WARNING app.ocr.paddle_adapter:normalize
   _paddle_output: unsupported raw type …` log line. That is the
   signal that a new shape landed.

3. The fix is to extend `normalize_paddle_output()` to recognise the
   new shape, plus add a test in `tests/test_paddleocr_output_formats.py`
   that pins the new shape.

The future-compatibility tests in
`tests/test_future_compatibility.py` already cover the "unknown shape"
path: the adapter returns `[]` and never crashes the cascade. The
goal is that no operator has to do anything on a PaddleOCR upgrade
**other than** extending the normaliser when the shape changes.

---

## 6. Detecting a new PaddleX / PP-Structure payload shape

Same pattern, see `app/ocr/structure_adapter.normalize_structure_output()`.
The function already accepts the three known keys:

* `parsing_res_list` (canonical V2)
* `layout_parsing_res_list` (V3 alternative)
* `layout_res_list` (older)
* `regions` (older still)

The function falls back to an empty result when none of those keys are
present, and the cascade handles it gracefully.

---

## 7. Rollback policy

Every new profile ships with **at least three** settings that allow the
operator to roll back **without a code change**:

| Rollback goal | Flag |
|---|---|
| Force the legacy `ocr()` API | `PADDLE_FORCE_LEGACY_OCR_API=true` |
| Disable PaddleOCR entirely | `OCR_ENGINE=tesseract` |
| Disable PP-Structure Tier 3 | `OCR_CASCADING_USE_PP_STRUCTURE=false` |
| Force V2 layout_parsing instead of V3 | `PP_STRUCTURE_FORCE_PADDLEX_FALLBACK=true` |
| Pin a known-good profile | `PADDLE_OCR_PROFILE=ppocr_v6_medium` |

When a profile misbehaves, the operator flips the relevant flags in
`.env.production`, restarts the workers, and the cascade is back to
the previous behaviour. No git revert needed.

If a profile is fundamentally broken (e.g. a model returns empty on
all inputs), the operator can also remove the profile id from
`model_registry.py` and pin a different id via the setting. The
unknown-id fallback returns the default profile with a WARNING.

---

## 8. Tests that pin the contract

These tests fail loudly when a future PaddleOCR / PaddleX upgrade
breaks the adapters. They must stay green:

* `tests/test_model_registry.py` — profile catalogue, unknown-id
  fallback, ENV overrides.
* `tests/test_paddle_adapter.py` — predict vs ocr, output normalisation,
  lazy init.
* `tests/test_structure_adapter.py` — V3 vs fallback, GPU refusal,
  markdown export.
* `tests/test_paddleocr_output_formats.py` — every known PaddleOCR
  output shape (predict dict, legacy list, object, generator, unknown).
* `tests/test_predict_ocr_fallback.py` — predict preferred, ocr
  fallback on missing / failure, no-API engines.
* `tests/test_future_compatibility.py` — new top-level shapes, new
  keys, unknown payloads.

When you add a new shape to the normaliser, add a test for it to the
relevant file. The CI must stay green.

---

## 9. What is explicitly out of scope

* **PaddleOCR-VL.** A multimodal OCR model. We do not introduce it.
  When the operator wants to opt in, that is a separate `O7`-style
  task with its own adapter (probably `paddle_vl_adapter.py`).
* **PaddleServing / PaddleX serving mode.** The adapter runs
  `PaddleOCR(...)` in-process. Deploying a separate OCR service is a
  separate infra decision.
* **Cloud-OCR providers (Google Document AI, AWS Textract, Azure
  Form Recognizer).** Out of scope. The registry's `OcrProfile.backend`
  field is `"paddleocr"` today but a future cloud-OCR profile would
  add its own backend value without changing the adapter contract.