"""Debug why PDFs get ocr_engine='empty'."""
from pathlib import Path
from app.ocr.factory import get_ocr_engine
from app.parsers.pdf import _render_page_to_image
import fitz

engine = get_ocr_engine()

pdf_path = Path("/app/data/files/19/1971e5d6dfe3e0f994b6417ee386bb7b4525b98eef870c33f9eb86df6b3468e4.pdf")
print(f"PDF: {pdf_path.name} ({pdf_path.stat().st_size} bytes)")

doc = fitz.open(str(pdf_path))
page = doc[0]
print(f"Page size: {page.rect.width:.0f}x{page.rect.height:.0f}")

text = page.get_text()
print(f"Extractable text: {len(text)} chars")

# Rasterize to temp dir
output_dir = Path("/tmp/ocr_debug")
output_dir.mkdir(exist_ok=True)

# Use the page object directly
img_path = output_dir / "page0"
result_path = _render_page_to_image(page, img_path, dpi=144)
print(f"Rasterize returned: {result_path}")

# Check what files exist
import os
for f in os.listdir(output_dir):
    fp = output_dir / f
    print(f"  {f}: {fp.stat().st_size} bytes")

# Find the actual image
for ext in [".jpg", ".jpeg", ".png"]:
    candidate = output_dir / f"page0{ext}"
    if candidate.exists():
        print(f"\nFound image: {candidate} ({candidate.stat().st_size} bytes)")
        ocr_result = engine.extract(candidate)
        print(f"OCR engine: {ocr_result.engine}")
        print(f"OCR confidence: {ocr_result.confidence}")
        print(f"OCR text length: {len(ocr_result.text or '')}")
        if ocr_result.text:
            print(f"Text: {ocr_result.text[:300]}")
        else:
            print("OCR returned EMPTY text!")
        break

doc.close()
