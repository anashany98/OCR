"""Debug why PDFs get ocr_engine='empty'."""
from pathlib import Path
from app.ocr.factory import get_ocr_engine
from app.parsers.pdf import _render_page_to_image, _ocr_scanned_page_by_index
import fitz  # PyMuPDF

engine = get_ocr_engine()

pdf_path = Path("/app/data/files/19/1971e5d6dfe3e0f994b6417ee386bb7b4525b98eef870c33f9eb86df6b3468e4.pdf")
print(f"PDF: {pdf_path.name} ({pdf_path.stat().st_size} bytes)")

# Check page count
doc = fitz.open(str(pdf_path))
print(f"Pages: {len(doc)}")
page = doc[0]
print(f"Page size: {page.rect.width:.0f}x{page.rect.height:.0f}")
text = page.get_text()
print(f"Extractable text: {len(text)} chars")
if text.strip():
    print(f"Text preview: {text[:200]}")
doc.close()

# Rasterize and try OCR
output_dir = Path("/tmp/ocr_debug")
output_dir.mkdir(exist_ok=True)
img_path = output_dir / "page0.png"
_render_page_to_image(doc[0] if hasattr(doc, '__getitem__') else fitz.open(str(pdf_path))[0], img_path, dpi=144)
print(f"\nRasterized: {img_path.exists()} ({img_path.stat().st_size if img_path.exists() else 0} bytes)")

if img_path.exists():
    result = engine.extract(img_path)
    print(f"OCR engine: {result.engine}")
    print(f"OCR confidence: {result.confidence}")
    print(f"OCR text length: {len(result.text or '')}")
    print(f"OCR blocks: {len(result.blocks)}")
    if result.text:
        print(f"Text preview: {result.text[:300]}")
