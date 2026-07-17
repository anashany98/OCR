# ruff: noqa: I001  # conditional package/direct imports are intentional for Docker and tests
"""Internal FastAPI boundary for OvisOCR2 page inference."""

from __future__ import annotations

import asyncio
import hmac
import io
import json
import logging
import os
import re
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import (
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.concurrency import run_in_threadpool
from PIL import Image, UnidentifiedImageError

try:  # Docker runs ``uvicorn app:app``; tests import the package path.
    from .model import OvisOCR2Model
    from .schemas import (
        OvisOCR2Block,
        OvisOCR2Readiness,
        OvisOCR2Response,
        SCHEMA_VERSION,
    )
except ImportError:  # pragma: no cover - exercised only by the container entrypoint
    from model import OvisOCR2Model
    from schemas import (
        OvisOCR2Block,
        OvisOCR2Readiness,
        OvisOCR2Response,
        SCHEMA_VERSION,
    )

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(), format="%(message)s"
)
logger = logging.getLogger("ovisocr2.app")
MAX_IMAGE_BYTES = int(os.environ.get("OVISOCR2_MAX_IMAGE_BYTES", str(32 * 1024 * 1024)))
MAX_PIXELS = int(os.environ.get("OVISOCR2_MAX_PIXELS", str(2880 * 2880)))
MIN_PIXELS = int(os.environ.get("OVISOCR2_MIN_PIXELS", str(448 * 448)))
MAX_TOKENS = int(os.environ.get("OVISOCR2_MAX_TOKENS", "16384"))
MAX_CONCURRENCY = int(os.environ.get("OVISOCR2_MAX_CONCURRENCY", "1"))
API_KEY = os.environ.get("OVISOCR2_API_KEY", "")
Image.MAX_IMAGE_PIXELS = MAX_PIXELS

_BBOX_RE = re.compile(
    r'<img\s+[^>]*?src\s*=\s*["\']images/bbox_(\d+)_(\d+)_(\d+)_(\d+)\.(?:jpg|jpeg|png)["\'][^>]*>',
    re.IGNORECASE,
)
_TABLE_RE = re.compile(r"<table\b[^>]*>.*?</table\s*>", re.IGNORECASE | re.DOTALL)
_FORMULA_RE = re.compile(r"(?:\$\$.+?\$\$|\\\[.+?\\\])", re.DOTALL)


def _json_log(event: str, **fields: object) -> None:
    logger.info(
        json.dumps(
            {"event": event, **fields}, ensure_ascii=False, separators=(",", ":")
        )
    )


def _authorise(authorization: str | None) -> None:
    if not API_KEY:
        return
    expected = f"Bearer {API_KEY}"
    if not authorization or not hmac.compare_digest(authorization, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid bearer token"
        )


async def _validated_image(upload: UploadFile) -> tuple[Image.Image, int, int, int]:
    content = await upload.read(MAX_IMAGE_BYTES + 1)
    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=422, detail="image exceeds byte limit")
    if not content:
        raise HTTPException(status_code=422, detail="image is empty")
    try:
        with Image.open(io.BytesIO(content)) as probe:
            probe.verify()
        with Image.open(io.BytesIO(content)) as opened:
            if opened.format not in {"JPEG", "PNG", "TIFF", "BMP", "WEBP"}:
                raise HTTPException(status_code=422, detail="unsupported image format")
            width, height = opened.size
            pixels = width * height
            if pixels < MIN_PIXELS or pixels > MAX_PIXELS:
                raise HTTPException(
                    status_code=422, detail="image pixels outside configured bounds"
                )
            return opened.convert("RGB"), width, height, pixels
    except HTTPException:
        raise
    except (
        UnidentifiedImageError,
        Image.DecompressionBombError,
        OSError,
        ValueError,
    ) as exc:
        raise HTTPException(status_code=422, detail="invalid image") from exc


def _blocks(markdown: str) -> list[OvisOCR2Block]:
    blocks: list[OvisOCR2Block] = (
        [OvisOCR2Block(type="text", text=markdown)] if markdown else []
    )
    blocks.extend(
        OvisOCR2Block(type="table", text=value) for value in _TABLE_RE.findall(markdown)
    )
    blocks.extend(
        OvisOCR2Block(type="formula", text=value)
        for value in _FORMULA_RE.findall(markdown)
    )
    for left, top, right, bottom in _BBOX_RE.findall(markdown):
        coords = tuple(float(value) for value in (left, top, right, bottom))
        if coords[2] > coords[0] and coords[3] > coords[1]:
            blocks.append(
                OvisOCR2Block(type="figure", text="visual_region", bbox_norm=coords)
            )
    return blocks[:512]


@asynccontextmanager
async def lifespan(app: FastAPI):
    runtime = OvisOCR2Model()
    app.state.runtime = runtime
    app.state.semaphore = asyncio.Semaphore(max(1, MAX_CONCURRENCY))
    runtime.start_loading()
    yield
    runtime.shutdown()


app = FastAPI(
    title="Docu-Intel OvisOCR2",
    version=SCHEMA_VERSION,
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz", response_model=OvisOCR2Readiness)
async def readyz(request: Request) -> OvisOCR2Readiness:
    runtime: OvisOCR2Model = request.app.state.runtime
    response = OvisOCR2Readiness(
        status=runtime.state,
        model=runtime.model_name,
        revision=runtime.revision,
        detail=runtime.detail if runtime.state == "failed" else None,
    )
    if runtime.state != "ready":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=response.model_dump(),
        )
    return response


@app.post("/v1/ocr", response_model=OvisOCR2Response)
async def ocr(
    request: Request,
    image: UploadFile = File(...),
    schema_version: str = Form(SCHEMA_VERSION),
    request_id: str = Form(""),
    document_id: str = Form(""),
    page_number: str = Form(""),
    max_tokens: int = Form(MAX_TOKENS),
    authorization: str | None = Header(default=None),
) -> OvisOCR2Response:
    _authorise(authorization)
    if schema_version != SCHEMA_VERSION:
        raise HTTPException(status_code=422, detail="unsupported schema_version")
    if max_tokens < 1 or max_tokens > MAX_TOKENS:
        raise HTTPException(status_code=422, detail="max_tokens outside allowed bounds")
    try:
        parsed_request_id = (
            str(uuid.UUID(request_id)) if request_id else str(uuid.uuid4())
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail="request_id must be a UUID"
        ) from exc
    runtime: OvisOCR2Model = request.app.state.runtime
    if runtime.state != "ready":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="model is not ready"
        )
    image_value, width, height, pixels = await _validated_image(image)
    semaphore: asyncio.Semaphore = request.app.state.semaphore
    try:
        await asyncio.wait_for(semaphore.acquire(), timeout=0.05)
    except TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="service saturated"
        ) from exc
    started = time.perf_counter()
    try:
        output = await run_in_threadpool(runtime.parse, image_value, max_tokens)
    except Exception as exc:  # noqa: BLE001 - never expose CUDA/internal paths to caller
        _json_log(
            "ovisocr2_inference_failed",
            request_id=parsed_request_id,
            error=type(exc).__name__,
        )
        raise HTTPException(status_code=500, detail="inference failed") from exc
    finally:
        semaphore.release()
    latency_ms = int((time.perf_counter() - started) * 1000)
    warnings = ["truncated_output"] if output.finish_reason == "length" else []
    _json_log(
        "ovisocr2_inference_completed",
        request_id=parsed_request_id,
        document_id=document_id or None,
        page_number=page_number or None,
        revision=runtime.revision,
        latency_ms=latency_ms,
        input_pixels=pixels,
        output_tokens=output.output_tokens,
        finish_reason=output.finish_reason,
    )
    return OvisOCR2Response(
        request_id=parsed_request_id,
        model=runtime.model_name,
        revision=runtime.revision,
        markdown=output.markdown,
        blocks=_blocks(output.markdown),
        finish_reason=output.finish_reason,
        input_pixels=pixels,
        output_tokens=output.output_tokens,
        latency_ms=latency_ms,
        warnings=warnings,
    )
