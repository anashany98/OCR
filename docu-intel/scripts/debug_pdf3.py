"""Debug why PDFs get ocr_engine='empty'."""
from pathlib import Path
from app.ocr.factory import get_ocr_engine
from app.parsers.pdf import _render_page_to_image
import fitz

engine = get_ocr_engine()

pdf_path = Path("/app/data/files/19/1971e5d6dfe3e0f994b6417ee386bb7b4525b98eef870c33f9eb86df6b3468e4.pdf")
print(f"PDF: {pdf_path.name} ({pdf_path.stat().st_size} bytes)")

doc = fitz.open(str(pdf_path))
print(f"Pages: {len(doc)}")
page = doc[0]
print(f"Page size: {page.rect.width:.0f}x{page.rect.height:.0f}")

# Check if text is extractable
text = page.get_text()
print(f"Extractable text: {len(text)} chars")
if text.strip():
    print(f"Text preview: {text[:200]}")

# Rasterize
output_dir = Path("/tmp/ocr_debug")
output_dir.mkdir(exist_ok=True)
img_path = output_dir / "page0.png"
result_path = _render_page_to_image(page, img_path, dpi=144)
print(f"Rasterized to: {result_path}")

if result_path and Path(result_path).exists():
    print(f"Image size: {Path(result_path).stat().st_size} bytes")
    # Try OCR
    ocr_result = engine.extract(Path(result_path))
    print(f"\nOCR engine: {ocr_result.engine}")
    print(f"OCR confidence: {ocr_result.confidence}")
    print(f"OCR text length: {len(ocr_result.text or '')}")
    print(f"OCR blocks: {len(ocr_result.blocks)}")
    if ocr_result.text:
        print(f"Text preview: {ocr_result.text[:300]}")
    else:
        print("OCR returned EMPTY text!")
else:
    print("Rasterization failed!")

doc.close()
