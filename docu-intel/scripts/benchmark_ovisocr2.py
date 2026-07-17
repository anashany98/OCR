"""Run the pinned OvisOCR2 adapter over an explicitly approved corpus manifest."""

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
    parser.add_argument("--dry-run", action="store_true")
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
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    pages = _pages(manifest)
    if args.limit:
        pages = pages[: args.limit]
    checked: list[dict] = []
    for ordinal, page in enumerate(pages, start=1):
        image = Path(str(page.get("image", "")))
        if not image.is_absolute():
            image = args.manifest.parent / image
        if not image.is_file():
            raise ValueError(f"manifest page {ordinal} image does not exist: {image}")
        checked.append(
            {
                "document_id": page.get("document_id"),
                "page_number": page.get("page_number"),
                "category": page.get("category", "unknown"),
                "image_sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                "image": str(image),
            }
        )
    if args.dry_run:
        output = {"mode": "dry_run", "manifest": str(args.manifest), "pages": checked, "count": len(checked)}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(output, indent=2), encoding="utf-8")
        print(json.dumps(output))
        return 0

    repository = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repository / "backend"))
    from app.ocr.ovisocr2 import OvisOCR2Config, OvisOCR2Engine

    config = OvisOCR2Config.from_settings()
    if not config.enabled:
        raise SystemExit("OVISOCR2_ENABLED must be true to benchmark the live service")
    engine = OvisOCR2Engine(config)
    results: list[dict] = []
    try:
        for item in checked:
            image = Path(item.pop("image"))
            engine.set_context(
                document_id=item["document_id"], page_number=item["page_number"], baseline=None
            )
            started = time.perf_counter()
            result = engine.extract(image)
            results.append(
                {
                    **item,
                    "engine": result.engine,
                    "engine_version": result.engine_version,
                    "latency_ms": int((time.perf_counter() - started) * 1000),
                    "text_sha256": hashlib.sha256(result.text.encode("utf-8")).hexdigest(),
                    "text_characters": len(result.text),
                    "warnings": result.warnings,
                    "blocks": {kind: sum(block.block_type == kind for block in result.blocks) for kind in ("table", "formula", "figure")},
                }
            )
    finally:
        engine.close()
    output = {"mode": "benchmark", "manifest": str(args.manifest), "pages": results, "count": len(results)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps({"count": len(results), "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
