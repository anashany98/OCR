"""S0.1 — Bootstrap the golden OCR fixture from real PDFs.

This script walks a directory of PDFs (default: ``C:\\Users\\PC\\Desktop\\TEST``),
extracts the text via PyMuPDF (the cascade's Tier 0 fast path), and
writes a per-PDF fixture directory under ``tests/fixtures/golden_ocr/``
with:

* a ``manifest.json`` listing the sample + its sha256 + a starter
  keyword list derived from the extracted text (importes, NIFs,
  numbers, dates);
* one ``page_N.txt`` per page with the extracted text used as
  *initial* ground truth.

The output is a working starting point, not a perfect golden set.
After running this script a human should review each ``page_N.txt``
and either accept it as ground truth (most pages) or correct it
(scan-only PDFs where the digital text is empty — those need a
real OCR pass first). Use ``scripts/update_golden_ocr.py`` to
re-bootstrap from the live OCR cascade once the fixtures are
in place.

Usage (from the backend/ directory):

    python -m scripts.build_golden_ocr
    python -m scripts.build_golden_ocr --source C:\\Users\\PC\\Desktop\\TEST
    python -m scripts.build_golden_ocr --out tests/fixtures/golden_ocr
    python -m scripts.build_golden_ocr --limit 5
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path

# Ensure the backend/ root is on sys.path so ``app.*`` imports work.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


logger = logging.getLogger("scripts.build_golden_ocr")


# Heuristics to mine a starter keyword list from the extracted text.
# These are substrings the OCR output is expected to recover and are
# the cheap, robust signal we use to detect regressions. A human
# reviewer should still curate the list per fixture.
_IMPORTE_RE = re.compile(r"\b\d{1,3}(?:[.,]\d{3})+(?:[.,]\d+)?\b|\b\d+[.,]\d{2}\b")
_DATE_RE = re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b")
_NIF_RE = re.compile(r"\b[ABCDEFGHJKLMNPQRSUVW]\d{7,8}\b")
_CIF_RE = re.compile(r"\b[ABCDEFGHJKLMNPQRSUVW]\d{7}[A-Z0-9]\b")
_SCALE_RE = re.compile(r"\b1\s*[:/]\s*\d{1,4}\b")
_ROOM_AREA_RE = re.compile(r"\b\d+(?:[.,]\d+)?\s*m\s*²?\b", re.IGNORECASE)


def _starter_keywords(text: str, max_keywords: int = 8) -> list[str]:
    """Pick a small, distinctive keyword set from the page text.

    Priority: NIFs/CIFs (very distinctive), dates, importes, room
    areas, scales. Duplicates removed; order = first-seen. We
    normalise every keyword (collapse whitespace, strip) so the
    substring matcher in the scorer cannot be fooled by line breaks
    inside a token.
    """
    if not text:
        return []
    # Normalise once, line by line, so regexes see clean text and
    # captured groups cannot contain stray newlines.
    normalised = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    seen: set[str] = set()
    keywords: list[str] = []
    for pattern in (_NIF_RE, _CIF_RE, _DATE_RE, _IMPORTE_RE, _SCALE_RE, _ROOM_AREA_RE):
        for match in pattern.finditer(normalised):
            value = re.sub(r"\s+", " ", match.group(0).strip())
            if not value or value in seen:
                continue
            seen.add(value)
            keywords.append(value)
            if len(keywords) >= max_keywords:
                return keywords
    return keywords


def _safe_id(filename: str) -> str:
    """Normalise a PDF filename to a stable directory id.

    Lower-cases, replaces spaces and non-alphanumerics with underscores,
    collapses runs of underscores.
    """
    stem = Path(filename).stem
    cleaned = re.sub(r"[^a-z0-9]+", "_", stem.lower()).strip("_")
    return cleaned or "sample"


def _infer_document_type(filename: str) -> str:
    """Best-effort type guess from the filename. The reviewer can fix
    the manifest afterwards."""
    lower = filename.lower()
    if "albaran" in lower:
        return "albaran"
    if (
        "presupuest" in lower
        or "precio" in lower
        or "hoja de confec" in lower
        or "memoria" in lower
    ):
        return "presupuesto"
    if "pedido" in lower or "pv" in lower or "venta" in lower:
        return "pedido"
    if (
        "plano" in lower
        or "escritorio" in lower
        or "medici" in lower
        or "bancada" in lower
        or "dtm" in lower
    ):
        return "plano"
    if "factura" in lower:
        return "factura"
    return "otro"


def _extract_pages_with_pymupdf(pdf_path: Path) -> list[str]:
    """Tier-0 fast path: read the embedded text per page. Returns one
    string per page. Empty strings mean the page is a scan (and the
    ground truth will need to be filled in by a real OCR run)."""
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "PyMuPDF is required: pip install pymupdf\n" f"Original import error: {exc}"
        ) from exc
    pages: list[str] = []
    with fitz.open(pdf_path) as doc:
        for page in doc:
            text = page.get_text("text").strip()
            pages.append(text)
    return pages


def build_one(
    pdf_path: Path,
    *,
    out_root: Path,
) -> tuple[str, int, list[str]]:
    """Build the fixture for a single PDF. Returns (id, pages_extracted, keywords)."""
    from app.services.golden_ocr import GoldenSample, sha256_of_file

    file_id = _safe_id(pdf_path.name)
    fixture_dir = out_root / file_id
    fixture_dir.mkdir(parents=True, exist_ok=True)

    pages = _extract_pages_with_pymupdf(pdf_path)
    all_text = "\n\n".join(pages)
    keywords = _starter_keywords(all_text)

    sample = GoldenSample(
        id=file_id,
        source_filename=pdf_path.name,
        document_type=_infer_document_type(pdf_path.name),
        page_count=len(pages),
        sha256=sha256_of_file(pdf_path),
        keywords=keywords,
    )
    (fixture_dir / "manifest.json").write_text(
        json.dumps({"samples": [sample.to_dict()]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    for n, text in enumerate(pages, start=1):
        (fixture_dir / f"page_{n}.txt").write_text(text, encoding="utf-8")

    return file_id, len(pages), keywords


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bootstrap the golden OCR fixture.")
    parser.add_argument(
        "--source",
        default=r"C:\Users\PC\Desktop\TEST",
        help="Directory containing the source PDFs.",
    )
    parser.add_argument(
        "--out",
        default=str(BACKEND_ROOT / "tests" / "fixtures" / "golden_ocr"),
        help="Output root for the per-PDF fixture directories.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="If > 0, stop after this many PDFs (useful for smoke tests).",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    source = Path(args.source)
    if not source.exists():
        logger.error("Source directory does not exist: %s", source)
        return 2
    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)

    pdfs = sorted(p for p in source.iterdir() if p.suffix.lower() == ".pdf")
    if not pdfs:
        logger.error("No PDFs found in %s", source)
        return 2
    if args.limit:
        pdfs = pdfs[: args.limit]

    logger.info("Bootstrapping %d fixtures into %s", len(pdfs), out_root)
    summary: list[tuple[str, int, int, list[str]]] = []
    for pdf in pdfs:
        try:
            file_id, n_pages, kws = build_one(pdf, out_root=out_root)
        except Exception as exc:  # pragma: no cover
            logger.error("Failed on %s: %s", pdf.name, exc)
            continue
        summary.append((file_id, n_pages, len(kws), kws))
        logger.info(
            "  %s: %d pages, %d starter keywords",
            file_id,
            n_pages,
            len(kws),
        )

    print()
    print(f"Built {len(summary)} fixtures in {out_root}")
    print("=" * 80)
    print("NEXT STEPS:")
    print("  1. Review each tests/fixtures/golden_ocr/<id>/page_*.txt file.")
    print("     PDFs without digital text will have empty pages — these")
    print("     need a real OCR pass to produce ground truth:")
    print("       python -m scripts.update_golden_ocr --force")
    print("  2. Curate the starter 'keywords' list in each manifest.json")
    print("     (add room names, scales, part numbers, etc.).")
    print("  3. Run the test suite to lock the baseline:")
    print("       pytest backend/tests/test_golden_ocr.py -v")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
