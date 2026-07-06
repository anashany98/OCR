"""Debug why a PDF gets ocr_engine='empty' and ocr_confidence=0."""
from pathlib import Path
from app.ocr.factory import get_ocr_engine
from app.parsers.pdf import _rasterize_page

engine = get_ocr_engine()

pdf_path = Path("/app/data/files/19/1971e5d6dfe3e0f994b6417ee386bb7b4525b98eef870c33f9eb86df6b3468e4.pdf")
print(f"PDF exists: {pdf_path.exists()}")
print(f"PDF size: {pdf_path.stat().st_size} bytes")

# Rasterize page 0
output_dir = Path("/tmp/test_ocr_debug")
output_dir.mkdir(exist_ok=True)
pages = _rasterize_page(pdf_path, 0, output_dir)
print(f"Rasterized pages: {pages}")

if pages:
    img_path = Path(pages[0]) if isinstance(pages[0], str) else pages[0]
    print(f"Image exists: {img_path.exists()}, size: {img_path.stat().st_size if img_path.exists() else 0}")

    # Try primary OCR (Tesseract)
    try:
        result = engine.primary.extract(img_path)
        print(f"Primary ({result.engine}): text_len={len(result.text or '')} conf={result.confidence}")
        print(f"  text preview: {(result.text or '')[:200]}")
    except Exception as e:
        print(f"Primary failed: {type(e).__name__}: {e}")

    # Try fallback OCR (PaddleOCR)
    try:
        result = engine.fallback.extract(img_path)
        print(f"Fallback ({result.engine}): text_len={len(result.text or '')} conf={result.confidence}")
        print(f"  text preview: {(result.text or '')[:200]}")
    except Exception as e:
        print(f"Fallback failed: {type(e).__name__}: {e}")

    # Try full cascade
    try:
        result = engine.extract(img_path)
        print(f"Cascade ({result.engine}): text_len={len(result.text or '')} conf={result.confidence}")
    except Exception as e:
        print(f"Cascade failed: {type(e).__name__}: {e}")
else:
    print("No pages rasterized")
