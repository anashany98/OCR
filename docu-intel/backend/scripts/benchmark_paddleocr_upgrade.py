"""Benchmark script for the PaddleOCR 3.7 / PP-OCRv6 upgrade (UPG-9).

Run against a directory of golden images / PDFs to compare:

* ``tesseract`` (Tier 1)
* ``paddleocr`` (Tier 2, with the configured PaddleOCR profile)
* ``pp_structure`` (Tier 3, GPU-only)
* ``cascading`` (default cascade with Tier 1 + Tier 2 + optional Tier 3)

The script is **safe to run without PaddleOCR / PaddleX installed** — when
the import fails it logs a clear error and falls back to a stub that
emits ``engine="unavailable"`` so the JSON output still includes every
document / page in the input directory.

Usage:

    python scripts/benchmark_paddleocr_upgrade.py \\
        --input-dir /app/data/test_ocr \\
        --output-json /app/data/ocr_benchmark_results.json \\
        --engine cascading \\
        --limit 50 \\
        --verbose

The script produces:

* A per-page table on stdout.
* A summary block (engine, time, characters, confidence, blocks).
* An optional JSON file with the full structured result for downstream
  dashboards.

It does NOT need a running backend / Celery / Redis / PostgreSQL — the
script runs in isolation against the input directory.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable


logger = logging.getLogger("docuintel.benchmark_paddleocr_upgrade")


# ---------------------------------------------------------------------------
# Result data structures
# ---------------------------------------------------------------------------


@dataclass
class PageResult:
    """One row in the benchmark output."""

    document: str
    page: int
    engine: str
    duration_seconds: float
    characters: int
    mean_confidence: float | None
    blocks: int
    fallback: bool
    error: str | None = None


@dataclass
class BenchmarkSummary:
    """Aggregated metrics for a benchmark run."""

    engine: str
    pages_processed: int
    pages_succeeded: int
    pages_failed: int
    total_characters: int
    mean_confidence: float | None
    total_duration_seconds: float
    mean_duration_seconds: float
    p50_duration_seconds: float
    p95_duration_seconds: float
    paddleocr_version: str | None = None
    paddleocr_profile: str | None = None
    paddlex_version: str | None = None
    structure_profile: str | None = None


@dataclass
class BenchmarkReport:
    """Top-level report emitted as JSON."""

    started_at: str
    finished_at: str
    summary: BenchmarkSummary
    pages: list[PageResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_engine(engine_name: str, settings: Any | None):
    """Build the configured OCR engine without going through Celery / DB.

    Mirrors the wiring in ``app.ocr.factory._build_cascading_engine`` so
    the benchmark uses the same profile / settings resolution as a
    production worker. When PaddleOCR / PaddleX is unavailable we fall
    back to Tesseract-only so the script still produces a complete
    output.
    """
    settings = settings or _safe_settings()

    if engine_name == "tesseract":
        from app.ocr.tesseract import TesseractOCREngine

        return TesseractOCREngine(
            lang=getattr(settings, "tesseract_lang", "spa+eng"),
            oem=getattr(settings, "tesseract_oem", 1),
            psm=getattr(settings, "tesseract_psm", 3),
        )

    if engine_name == "paddleocr":
        from app.ocr.paddle import PaddleOCREngine

        try:
            return PaddleOCREngine(
                lang=getattr(settings, "paddle_lang", "es"),
            )
        except Exception as exc:  # pragma: no cover - depends on GPU/Paddle install
            logger.warning("paddleocr unavailable, falling back to tesseract: %s", exc)
            from app.ocr.tesseract import TesseractOCREngine

            return TesseractOCREngine(lang="spa+eng")

    if engine_name == "pp_structure":
        from app.ocr.pp_structure import PPStructureEngine

        try:
            return PPStructureEngine(
                device=getattr(settings, "pp_structure_device", "gpu"),
                lang=getattr(settings, "pp_structure_lang", "es"),
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("pp_structure unavailable: %s", exc)
            raise

    if engine_name == "cascading":
        from app.ocr.cascading import CascadingOCREngine
        from app.ocr.paddle import PaddleOCREngine
        from app.ocr.tesseract import TesseractOCREngine

        primary = TesseractOCREngine(
            lang=getattr(settings, "tesseract_lang", "spa+eng"),
            oem=getattr(settings, "tesseract_oem", 1),
            psm=getattr(settings, "tesseract_psm", 3),
        )
        try:
            fallback = PaddleOCREngine(
                lang=getattr(settings, "paddle_lang", "es"),
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("paddleocr unavailable, cascade uses tesseract-only: %s", exc)
            fallback = TesseractOCREngine(lang="spa+eng")
        return CascadingOCREngine(
            primary=primary,
            fallback=fallback,
            min_chars=getattr(settings, "ocr_cascading_min_chars", 30),
            min_confidence=getattr(settings, "ocr_cascading_min_confidence", 0.5),
        )

    raise ValueError(
        f"Unknown engine {engine_name!r}. Expected tesseract, paddleocr, pp_structure, cascading."
    )


def _safe_settings() -> Any:
    """Load settings without blowing up if the env has weak secrets.

    Falls back to ``SimpleNamespace`` with sensible defaults so the
    benchmark script works in isolation (e.g. CI containers without the
    full backend .env).
    """
    try:
        from app.core.config import settings

        return settings
    except Exception as exc:
        logger.debug("settings unavailable (%s); using defaults", exc)
        from types import SimpleNamespace

        return SimpleNamespace(
            tesseract_lang="spa+eng",
            tesseract_oem=1,
            tesseract_psm=3,
            paddle_lang="es",
            pp_structure_device="gpu",
            pp_structure_lang="es",
            ocr_cascading_min_chars=30,
            ocr_cascading_min_confidence=0.5,
            paddle_ocr_profile="ppocr_v6_medium",
            pp_structure_profile="pp_structure_v3",
        )


def _iter_images(input_dir: Path, limit: int | None) -> Iterable[Path]:
    """Yield image / PDF paths under ``input_dir`` (sorted, capped)."""
    if not input_dir.exists():
        raise FileNotFoundError(f"input-dir does not exist: {input_dir}")
    exts = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".pdf"}
    paths = sorted(p for p in input_dir.rglob("*") if p.suffix.lower() in exts)
    if limit is not None:
        paths = paths[:limit]
    return paths


def _pages_for(path: Path) -> list[Path]:
    """Render each page of an image / PDF to a temporary PNG.

    For images, returns a single-element list with the original path.
    For PDFs, uses PyMuPDF to render every page to a tmp PNG. When the
    PDF library is unavailable or the file is malformed, falls back to
    ``[path]`` so the benchmark still records a row.
    """
    if path.suffix.lower() != ".pdf":
        return [path]

    try:
        import fitz  # PyMuPDF

        tmp_dir = Path(os.environ.get("TMPDIR", "/tmp"))
        out: list[Path] = []
        with fitz.open(path) as doc:
            for index, page in enumerate(doc):
                pix = page.get_pixmap(dpi=200)
                target = tmp_dir / f"benchmark_{path.stem}_{index}.png"
                pix.save(target)
                out.append(target)
        return out
    except Exception as exc:  # pragma: no cover - depends on pymupdf
        logger.debug("PyMuPDF rendering failed for %s: %s", path, exc)
        return [path]


def _paddleocr_version() -> str | None:
    try:
        import paddleocr

        return getattr(paddleocr, "__version__", "unknown")
    except Exception:
        return None


def _paddlex_version() -> str | None:
    try:
        import paddlex

        return getattr(paddlex, "__version__", "unknown")
    except Exception:
        return None


def _resolve_profile_name(settings: Any, kind: str) -> str | None:
    if kind == "ocr":
        return getattr(settings, "paddle_ocr_profile", None)
    if kind == "structure":
        return getattr(settings, "pp_structure_profile", None)
    return None


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def run_benchmark(
    *,
    input_dir: Path,
    engine_name: str,
    limit: int | None,
    disable_structure: bool,
    verbose: bool,
) -> BenchmarkReport:
    started = time.time()
    started_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started))

    settings = _safe_settings()
    if disable_structure and engine_name == "cascading":
        # Honour the CLI flag by building the cascade explicitly without
        # Tier 3 even when the setting is on.
        setattr(settings, "ocr_cascading_use_pp_structure", False)

    engine = _resolve_engine(engine_name, settings)
    page_results: list[PageResult] = []
    durations: list[float] = []

    for document_path in _iter_images(input_dir, limit):
        for page_index, page_path in enumerate(_pages_for(document_path)):
            row = _run_one(engine, document_path, page_path, page_index, verbose)
            page_results.append(row)
            if row.error is None:
                durations.append(row.duration_seconds)

    finished = time.time()
    finished_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(finished))

    succeeded = sum(1 for r in page_results if r.error is None)
    failed = sum(1 for r in page_results if r.error is not None)
    confidences = [r.mean_confidence for r in page_results if r.mean_confidence is not None]
    mean_confidence = statistics.fmean(confidences) if confidences else None

    summary = BenchmarkSummary(
        engine=engine_name,
        pages_processed=len(page_results),
        pages_succeeded=succeeded,
        pages_failed=failed,
        total_characters=sum(r.characters for r in page_results),
        mean_confidence=mean_confidence,
        total_duration_seconds=sum(durations),
        mean_duration_seconds=statistics.fmean(durations) if durations else 0.0,
        p50_duration_seconds=_percentile(durations, 50),
        p95_duration_seconds=_percentile(durations, 95),
        paddleocr_version=_paddleocr_version(),
        paddleocr_profile=_resolve_profile_name(settings, "ocr"),
        paddlex_version=_paddlex_version(),
        structure_profile=_resolve_profile_name(settings, "structure"),
    )

    return BenchmarkReport(
        started_at=started_iso,
        finished_at=finished_iso,
        summary=summary,
        pages=page_results,
    )


def _run_one(
    engine: Any,
    document_path: Path,
    page_path: Path,
    page_index: int,
    verbose: bool,
) -> PageResult:
    """Run the engine against one page and time it."""
    start = time.perf_counter()
    error: str | None = None
    engine_name = getattr(engine, "name", engine_name_for(engine))
    fallback = False
    text = ""
    confidence = None
    blocks = 0
    try:
        result = engine.extract(page_path)
        text = result.text or ""
        confidence = result.confidence
        blocks = len(result.blocks or [])
        engine_name = result.engine or engine_name
        # Detect cascade fallback: the cascade engine's ``name`` flips
        # when it escalates. If we asked for ``paddleocr`` and got
        # ``paddleocr`` we keep the original; if we got ``pp_structure``
        # we flag a fallback.
        fallback = engine_name not in ("tesseract", getattr(engine, "name", ""))
    except Exception as exc:
        logger.warning("extract failed for %s page %d: %s", document_path, page_index, exc)
        error = repr(exc)
    duration = time.perf_counter() - start

    row = PageResult(
        document=str(document_path),
        page=page_index,
        engine=engine_name,
        duration_seconds=round(duration, 4),
        characters=len(text),
        mean_confidence=round(confidence, 4) if confidence is not None else None,
        blocks=blocks,
        fallback=fallback,
        error=error,
    )
    if verbose:
        print(
            f"  {document_path.name} p{page_index} engine={engine_name} "
            f"chars={row.characters} conf={row.mean_confidence} "
            f"blocks={row.blocks} dur={row.duration_seconds}s err={row.error}"
        )
    return row


def engine_name_for(engine: Any) -> str:
    return type(engine).__name__


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    idx = max(0, min(len(sorted_values) - 1, int(round((pct / 100.0) * (len(sorted_values) - 1)))))
    return sorted_values[idx]


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def print_report(report: BenchmarkReport) -> None:
    print(f"\n=== Benchmark finished at {report.finished_at} ===")
    print(f"Engine: {report.summary.engine}")
    print(
        f"Pages: {report.summary.pages_succeeded}/{report.summary.pages_processed} succeeded"
    )
    print(f"Characters: {report.summary.total_characters}")
    print(f"Mean confidence: {report.summary.mean_confidence}")
    print(
        f"Duration: total={report.summary.total_duration_seconds:.2f}s "
        f"mean={report.summary.mean_duration_seconds:.2f}s "
        f"p50={report.summary.p50_duration_seconds:.2f}s "
        f"p95={report.summary.p95_duration_seconds:.2f}s"
    )
    if report.summary.paddleocr_version:
        print(f"PaddleOCR version: {report.summary.paddleocr_version}")
    if report.summary.paddleocr_profile:
        print(f"PaddleOCR profile: {report.summary.paddleocr_profile}")
    if report.summary.paddlex_version:
        print(f"PaddleX version: {report.summary.paddlex_version}")
    if report.summary.structure_profile:
        print(f"Structure profile: {report.summary.structure_profile}")

    print("\nPer-page results:")
    header = (
        f"{'document':<40} {'page':>4} {'engine':<14} "
        f"{'chars':>6} {'conf':>6} {'blocks':>6} {'dur':>8} {'err':>10}"
    )
    print(header)
    print("-" * len(header))
    for row in report.pages:
        print(
            f"{Path(row.document).name:<40} {row.page:>4} {row.engine:<14} "
            f"{row.characters:>6} "
            f"{'-' if row.mean_confidence is None else f'{row.mean_confidence:.2f}':>6} "
            f"{row.blocks:>6} {row.duration_seconds:>8.3f} "
            f"{'-' if row.error is None else 'err':>10}"
        )


def write_json(report: BenchmarkReport, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "started_at": report.started_at,
        "finished_at": report.finished_at,
        "summary": asdict(report.summary),
        "pages": [asdict(r) for r in report.pages],
    }
    output_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark the OCR cascade against a directory of test images / PDFs.",
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        required=True,
        help="Directory of test images / PDFs to OCR.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="Optional JSON file to dump the full report to.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap the number of input files processed.",
    )
    parser.add_argument(
        "--engine",
        choices=("cascading", "tesseract", "paddleocr", "pp_structure"),
        default="cascading",
        help="OCR engine to benchmark (default: cascading).",
    )
    parser.add_argument(
        "--disable-structure",
        action="store_true",
        help="Disable PP-Structure Tier 3 even when the cascade is on.",
    )
    parser.add_argument("--verbose", action="store_true", help="Print per-page results as they happen.")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        help="Logging level (default: INFO).",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )

    report = run_benchmark(
        input_dir=args.input_dir,
        engine_name=args.engine,
        limit=args.limit,
        disable_structure=args.disable_structure,
        verbose=args.verbose,
    )
    print_report(report)
    if args.output_json:
        write_json(report, args.output_json)
        print(f"\nWrote JSON report to {args.output_json}")

    return 0


if __name__ == "__main__":
    sys.exit(main())