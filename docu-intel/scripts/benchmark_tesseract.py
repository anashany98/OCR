"""Benchmark the existing Tesseract engine over an approved image manifest.

This produces the same page-level timing and redacted text measurements as
``benchmark_ovisocr2.py`` so operational cost can be compared without writing
OCR content to the benchmark artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0)
    return parser.parse_args()


def _pages(manifest: object) -> list[dict]:
    if isinstance(manifest, list) and all(isinstance(page, dict) for page in manifest):
        return manifest
    if isinstance(manifest, dict) and isinstance(manifest.get("pages"), list):
        pages = manifest["pages"]
        if all(isinstance(page, dict) for page in pages):
            return pages
    raise ValueError("manifest must be a list or an object with a pages list")


def main() -> int:
    args = _arguments()
    pages = _pages(json.loads(args.manifest.read_text(encoding="utf-8")))
    if args.limit:
        pages = pages[: args.limit]

    repository = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repository / "backend"))
    from app.ocr.tesseract import TesseractOCREngine

    engine = TesseractOCREngine()
    results: list[dict] = []
    for ordinal, page in enumerate(pages, start=1):
        image = Path(str(page.get("image", "")))
        if not image.is_absolute():
            image = args.manifest.parent / image
        if not image.is_file():
            raise ValueError(f"manifest page {ordinal} image does not exist: {image}")
        image_sha256 = hashlib.sha256(image.read_bytes()).hexdigest()
        started = time.perf_counter()
        result = engine.extract(image)
        results.append(
            {
                "document_id": page.get("document_id"),
                "page_number": page.get("page_number"),
                "category": page.get("category", "unknown"),
                "image_sha256": image_sha256,
                "engine": result.engine,
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "text_sha256": hashlib.sha256(result.text.encode("utf-8")).hexdigest(),
                "text_characters": len(result.text),
                "warnings": result.warnings,
            }
        )

    output = {"mode": "benchmark", "engine": "tesseract", "pages": results, "count": len(results)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps({"count": len(results), "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
