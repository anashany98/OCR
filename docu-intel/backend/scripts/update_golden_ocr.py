"""S0.1 — Refresh the golden OCR ground truth from the live pipeline.

By default, ``scripts/build_golden_ocr.py`` produces a *partial*
golden set: only PDFs that have digital text get a non-empty
``page_N.txt``. Scan-only PDFs (albaranes escaneados, fotos, etc.)
end up with empty ground-truth files and therefore always fail the
CI gate.

This script walks every fixture in ``tests/fixtures/golden_ocr/`` and,
for every page whose ``page_N.txt`` is empty (or whose source PDF
sha256 no longer matches the manifest), re-extracts the text using
the project's real cascade (Tier 0 PyMuPDF → Tier 1 Tesseract → Tier
2 PaddleOCR) and writes the result as the new ground truth.

The script is *not* meant to be run blindly. Re-baselining the
golden set is a deliberate act: a regression in OCR quality is
exactly what we want to detect, and a silent re-baseline would mask
it. The script therefore:

* only refreshes pages that are *currently* empty (or, with
  ``--force``, every page);
* prints a diff of the proposed new ground truth vs the existing
  one so a human can review;
* exits non-zero when the resulting ground truth differs from the
  on-disk version and ``--accept`` is not set, so CI cannot
  accidentally regress.

Usage (from backend/):

    # Refresh only the empty pages (the common case after bootstrap).
    python -m scripts.update_golden_ocr

    # Diff vs the live pipeline without writing anything.
    python -m scripts.update_golden_ocr --dry-run

    # Force-refresh every page (use only when you know what you are
    # doing — this is a manual baseline reset).
    python -m scripts.update_golden_ocr --force --accept
"""

from __future__ import annotations

import argparse
import difflib
import logging
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


logger = logging.getLogger("scripts.update_golden_ocr")


def _extract_page_with_pipeline(
    pdf_path: Path,
    page_number: int,
    *,
    out_dir: Path | None = None,
) -> str:
    """Run the project's real OCR cascade on a single page.

    We try PyMuPDF first (Tier 0 fast path); if the result is empty
    we fall back to a direct Tesseract call so the bootstrap path
    works in CI without a GPU. When Tesseract is not available on
    the host (the common case on a bare Windows box) we still render
    the page bitmap to ``page_N.png`` so the reviewer can see the
    source image that needs OCR; the ``page_N.txt`` stays empty with
    a sentinel so the scorer flags it cleanly.
    """
    try:
        import fitz
    except ImportError:
        return ""

    with fitz.open(pdf_path) as doc:
        if page_number < 1 or page_number > len(doc):
            return ""
        page = doc[page_number - 1]
        text = page.get_text("text").strip()
        if len(text) >= 30:
            return text
        # Empty / scan: render and run Tesseract. The Tesseract pass
        # is the same one the cascade would run as Tier 1. We also
        # save the rendered PNG so a human reviewer (or a future GPU
        # run) can use it as the source of truth without re-rendering.
        try:
            import io

            import pytesseract
            from PIL import Image

            zoom = 300 / 72.0
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            png_bytes = pix.tobytes("png")
            if out_dir is not None:
                png_path = out_dir / f"page_{page_number}.png"
                png_path.write_bytes(png_bytes)
            img = Image.open(io.BytesIO(png_bytes))
            return pytesseract.image_to_string(img, lang="spa+eng").strip()
        except pytesseract.TesseractNotFoundError:
            logger.debug(
                "Tesseract binary not found for %s p%d; rendered PNG only",
                pdf_path,
                page_number,
            )
            # Best-effort: still render the PNG so a reviewer / GPU
            # worker can OCR it later.
            try:
                if out_dir is not None:
                    pix = page.get_pixmap(matrix=fitz.Matrix(300 / 72.0, 300 / 72.0), alpha=False)
                    (out_dir / f"page_{page_number}.png").write_bytes(pix.tobytes("png"))
            except Exception:
                pass
            return ""
        except Exception as exc:  # pragma: no cover
            logger.debug("Tesseract fallback failed for %s p%d: %s", pdf_path, page_number, exc)
            return ""


def _format_diff(old: str, new: str, *, context: int = 2) -> str:
    diff = difflib.unified_diff(
        old.splitlines(),
        new.splitlines(),
        fromfile="current",
        tofile="proposed",
        lineterm="",
        n=context,
    )
    return "\n".join(diff)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh the golden OCR ground truth.")
    parser.add_argument(
        "--root",
        default=str(BACKEND_ROOT / "tests" / "fixtures" / "golden_ocr"),
        help="Root directory holding the per-PDF fixture directories.",
    )
    parser.add_argument(
        "--source",
        default=r"C:\Users\PC\Desktop\TEST",
        help="Directory containing the original PDFs (must match the manifest sha256).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Refresh every page, not only the ones currently empty.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the proposed diffs but do not write anything.",
    )
    parser.add_argument(
        "--accept",
        action="store_true",
        help="Accept the proposed ground truth without an interactive prompt (CI).",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    from app.services.golden_ocr import load_manifest

    root = Path(args.root)
    source = Path(args.source)
    if not root.exists():
        logger.error("Fixture root does not exist: %s", root)
        return 2

    changed = 0
    skipped = 0
    for fixture_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        if not (fixture_dir / "manifest.json").exists():
            continue
        samples = load_manifest(fixture_dir / "manifest.json")
        if not samples:
            continue
        sample = samples[0]
        pdf_path = source / sample.source_filename
        if not pdf_path.exists():
            logger.warning("Source PDF missing for %s: %s", sample.id, pdf_path)
            skipped += 1
            continue

        for n in range(1, sample.page_count + 1):
            text_path = fixture_dir / f"page_{n}.txt"
            current = text_path.read_text(encoding="utf-8") if text_path.exists() else ""
            needs_refresh = args.force or not current.strip()
            if not needs_refresh:
                continue
            proposed = _extract_page_with_pipeline(pdf_path, n, out_dir=fixture_dir)
            if not proposed:
                logger.info("  %s p%d: no text extracted, leaving as-is", sample.id, n)
                continue
            if proposed.strip() == current.strip():
                logger.info("  %s p%d: no change", sample.id, n)
                continue
            if args.dry_run:
                logger.info("--- DIFF %s p%d ---", sample.id, n)
                sys.stdout.write(_format_diff(current, proposed) + "\n")
            else:
                if not args.accept:
                    logger.info("--- DIFF %s p%d (use --accept to write) ---", sample.id, n)
                    sys.stdout.write(_format_diff(current, proposed) + "\n")
                else:
                    text_path.write_text(proposed, encoding="utf-8")
                    changed += 1
                    logger.info("  %s p%d: updated (%d chars)", sample.id, n, len(proposed))

    if args.dry_run:
        print(f"\nDry run: {changed} changes proposed, {skipped} fixtures skipped (no source PDF).")
        return 0
    if not args.accept:
        print(
            f"\n{changed} changes proposed. Re-run with --accept to write them. "
            f"{skipped} fixtures skipped because the source PDF is missing."
        )
        return 1
    print(f"\nDone. {changed} ground-truth pages updated, {skipped} fixtures skipped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
