"""Reproducible DXF/DWG parser benchmark.

This benchmark never writes to the application database. It walks a supplied
corpus, parses DXF files (and reports DWG converter failures), and emits a
stable JSON summary suitable for certification artifacts.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.parsers.router import parse_document  # noqa: E402


def benchmark(root: Path) -> dict:
    rows = []
    for path in sorted(p for p in root.rglob("*") if p.suffix.lower() in {".dxf", ".dwg"}):
        started = time.perf_counter()
        error = None
        extracted = None
        try:
            extracted = parse_document(path, root / ".cad_benchmark_output", None)
        except Exception as exc:  # converter absence is part of the report
            error = type(exc).__name__ + ": " + str(exc)
        elapsed = round(time.perf_counter() - started, 4)
        cad = extracted.cad if extracted else None
        rows.append(
            {
                "file": path.relative_to(root).as_posix(),
                "format": path.suffix.lower().lstrip("."),
                "seconds": elapsed,
                "error": error,
                "pages": len(extracted.pages) if extracted else 0,
                "texts": len(cad.texts) if cad else 0,
                "dimensions": len(cad.dimensions) if cad else 0,
                "geometry": len(cad.geometry) if cad else 0,
                "inserts": len(cad.inserts) if cad else 0,
                "layers": list(cad.metadata.layers) if cad else [],
            }
        )
    return {
        "corpus": str(root),
        "files": len(rows),
        "successful": sum(1 for row in rows if row["error"] is None),
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = benchmark(args.corpus)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("files", "successful")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
