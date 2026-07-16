"""Test PDF vector text extraction with our generated plan."""
import sys
sys.path.insert(0, 'backend')
from pathlib import Path
import fitz

pdf_path = Path('data/input/planos/vivienda_planta_baja.pdf')
with fitz.open(str(pdf_path)) as doc:
    for i, page in enumerate(doc):
        text = page.get_text('text')
        print(f'Page {i+1}: {len(text)} chars')
        print(text[:500])
        print()
        # Check for vector text with bounding boxes
        text_dict = page.get_text('dict')
        blocks = text_dict.get('blocks', [])
        print(f'  Vector blocks: {len(blocks)}')
        for b in blocks[:10]:
            if b['type'] == 0:  # text block
                for line in b.get('lines', []):
                    for span in line.get('spans', []):
                        print(f'    text="{span["text"]}" bbox={span["bbox"]} font={span["font"]} size={span["size"]:.1f}')
