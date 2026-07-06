# NuExtract3

NuExtract3 is an optional visual OCR and structured extraction provider. It runs outside the backend behind a vLLM OpenAI-compatible `/v1/chat/completions` endpoint.

It can:

- produce clean Markdown for hard OCR pages as Tier 4;
- extract structured JSON from page images using a JSON template.

It does not replace PaddleOCR or PP-Structure. NuExtract3 does not provide reliable bounding boxes, so PaddleOCR/PP-Structure remain the source for layout and coordinates.

## Start vLLM

```powershell
docker compose -f docker-compose.yml -f docs/docker-compose.nuextract.yml up -d nuextract-vllm
```

GPU recommendation:

- GPU 0: main LLM / embeddings.
- GPU 1: NuExtract3.

If vLLM fails with speculative decoding, remove `--speculative-config` from `docs/docker-compose.nuextract.yml` and retry. If it runs out of memory, lower `NUEXTRACT_MAX_IMAGES` and `--max-model-len`.

## Environment

```env
NUEXTRACT_ENABLED=false
NUEXTRACT_BASE_URL=http://nuextract-vllm:8000/v1
NUEXTRACT_MODEL=numind/NuExtract3
NUEXTRACT_TIMEOUT_SECONDS=120
NUEXTRACT_ENABLE_THINKING=false
NUEXTRACT_MAX_CONCURRENCY=1
NUEXTRACT_MAX_IMAGES=4
NUEXTRACT_MARKDOWN_TEMPERATURE=0.2
NUEXTRACT_EXTRACTION_TEMPERATURE=0.2
NUEXTRACT_TIER4_ENABLED=false
NUEXTRACT_HYPEREXTRACT_ENABLED=false
```

## Enable Tier 4 OCR

```env
OCR_ENGINE=cascading
NUEXTRACT_ENABLED=true
NUEXTRACT_TIER4_ENABLED=true
```

NuExtract3 only runs when the best Tier 1-3 OCR quality is below the cascade Tier 4 threshold. If NuExtract3 fails, the cascade keeps the prior result or uses `DotsMOCREngine` when configured.

## Enable HyperExtract visual

```env
HYPEREXTRACT_ENABLED=true
HYPEREXTRACT_PROVIDER=nuextract_visual
HYPEREXTRACT_RUN_IN_PIPELINE=true
NUEXTRACT_ENABLED=true
NUEXTRACT_HYPEREXTRACT_ENABLED=true
```

Initial recommended values:

- `NUEXTRACT_ENABLE_THINKING=false`
- `NUEXTRACT_MARKDOWN_TEMPERATURE=0.2`
- `NUEXTRACT_EXTRACTION_TEMPERATURE=0.2`
- `NUEXTRACT_MAX_CONCURRENCY=1`
- vLLM `--max-model-len 16384`
