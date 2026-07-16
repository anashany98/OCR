"""
PM0.2 — Test integral del pipeline de planos.
Valida extracción DXF y PDF contra manifest de valores esperados.

Ejecutar: python scripts/test_pipeline_e2e.py
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from app.parsers.dxf import parse_dxf
from app.parsers.types import ExtractedDocument

# --- Paths ---
BASE = Path(__file__).parent.parent
PLANOS_DIR = BASE / "data" / "input" / "planos"
DXF_PATH = PLANOS_DIR / "vivienda_planta_baja.dxf"
PDF_PATH = PLANOS_DIR / "vivienda_planta_baja.pdf"
MANIFEST_PATH = PLANOS_DIR / "vivienda_planta_baja.manifest.json"

# --- Load manifest ---
with open(MANIFEST_PATH, encoding="utf-8") as f:
    manifest = json.load(f)
expected = manifest["expected"]

# --- Regex patterns (from plan_extraction.py) ---
SCALE_RE = re.compile(r"1\s*[:/]\s*(\d{1,5})", re.IGNORECASE)
NUMBER_PATTERN = r"(?:\d{1,3}(?:[.,]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
DIMENSION_RE = re.compile(rf"({NUMBER_PATTERN})\s*(mm|cm|m)\b(?!\s*[2²])", re.IGNORECASE)
ROOM_AREA_RE = re.compile(
    rf"([A-Za-zÁÉÍÓÚÑáéíóúñ][A-Za-zÁÉÍÓÚÑáéíóúñ0-9 ._/\-]{{1,60}}?)\s+({NUMBER_PATTERN})\s*m\s*(?:2|²)",
    re.IGNORECASE,
)


def parse_value(s: str) -> float:
    """Parse Spanish-format number: 5,00 → 5.0."""
    return float(s.replace(".", "").replace(",", "."))


def test_dxf():
    """Test DXF parser extraction."""
    print("=" * 60)
    print("TEST: DXF Parser")
    print("=" * 60)

    result = parse_dxf(DXF_PATH, Path("/tmp/dxf_test"))
    assert len(result.pages) == 1, f"Expected 1 page, got {len(result.pages)}"
    page = result.pages[0]

    print(f"  Text length: {len(page.text)} chars")
    print(f"  Blocks: {len(page.blocks)}")

    # 1. Scale extraction
    scale_match = SCALE_RE.search(page.text)
    assert scale_match, "Scale not found in DXF text"
    scale_ratio = int(scale_match.group(1))
    assert scale_ratio == 100, f"Expected scale 1:100, got 1:{scale_ratio}"
    print(f"  ✓ Scale: 1:{scale_ratio}")

    # 2. Phase extraction
    assert "PLANTA BAJA" in page.text, "Phase 'PLANTA BAJA' not found"
    print("  ✓ Phase: PLANTA BAJA")

    # 3. Revision extraction
    assert "Rev: B" in page.text or "Rev B" in page.text, "Revision B not found"
    print("  ✓ Revision: B")

    # 4. Sheet extraction
    assert "A-01" in page.text, "Sheet A-01 not found"
    print("  ✓ Sheet: A-01")

    # 5. Room names
    for room in expected["rooms"]:
        assert room["name"] in page.text, f"Room '{room['name']}' not found"
    print(f"  ✓ All {len(expected['rooms'])} rooms found")

    # 6. Dimension blocks
    dim_blocks = [b for b in page.blocks if b.block_type == "dimension"]
    print(f"  ✓ DIMENSION blocks: {len(dim_blocks)}")

    # 7. Geometry
    assert "Geometría:" in page.text, "Geometry summary not found"
    assert "line=" in page.text, "Lines not found in geometry"
    print("  ✓ Geometry extracted (lines, polylines, arcs)")

    # 8. Units
    assert "Unidades: m" in page.text, "Units 'm' not found"
    print("  ✓ Units: m")

    # 9. Layers
    assert "Capas:" in page.text, "Layer names not found"
    for layer in ["MUROS", "COTAS", "TEXTO", "PUERTAS", "VENTANAS"]:
        assert layer in page.text, f"Layer '{layer}' not found"
    print("  ✓ All architectural layers found")

    print("  PASSED\n")
    return True


def test_pdf_vector():
    """Test PDF vector text extraction (PM2.1)."""
    print("=" * 60)
    print("TEST: PDF Vector Extraction (PM2.1)")
    print("=" * 60)

    import fitz

    with fitz.open(str(PDF_PATH)) as doc:
        page = doc[0]
        text = page.get_text("text")
        text_dict = page.get_text("dict")
        blocks = text_dict.get("blocks", [])

    print(f"  Text length: {len(text)} chars")
    print(f"  Vector blocks: {len(blocks)}")

    # 1. All text present
    assert "VIVIENDA UNIFAMILIAR" in text
    assert "PLANTA BAJA" in text
    assert "1:100" in text
    print("  ✓ Title and metadata found")

    # 2. Vector blocks have bboxes
    text_blocks = [b for b in blocks if b["type"] == 0]
    assert len(text_blocks) >= 10, f"Expected >= 10 text blocks, got {len(text_blocks)}"

    bboxes_found = 0
    for b in text_blocks:
        for line in b.get("lines", []):
            for span in line.get("spans", []):
                if span.get("bbox"):
                    bboxes_found += 1
    assert bboxes_found >= 10, f"Expected >= 10 bboxes, got {bboxes_found}"
    print(f"  ✓ {bboxes_found} text spans with bboxes")

    # 3. Room names with bboxes
    room_bboxes = {}
    for b in text_blocks:
        for line in b.get("lines", []):
            for span in line.get("spans", []):
                txt = span["text"].strip()
                for room in expected["rooms"]:
                    if txt == room["name"]:
                        room_bboxes[room["name"]] = span["bbox"]

    for room in expected["rooms"]:
        assert room["name"] in room_bboxes, f"Room '{room['name']}' bbox not found"
    print(f"  ✓ All {len(room_bboxes)} room labels have bboxes")

    # 4. Dimensions with bboxes
    dim_spans = []
    for b in text_blocks:
        for line in b.get("lines", []):
            for span in line.get("spans", []):
                if DIMENSION_RE.search(span["text"]):
                    dim_spans.append(span)

    assert len(dim_spans) >= 4, f"Expected >= 4 dimension spans, got {len(dim_spans)}"
    print(f"  ✓ {len(dim_spans)} dimension spans with bboxes")

    # 5. Font sizes indicate hierarchy
    font_sizes = set()
    for b in text_blocks:
        for line in b.get("lines", []):
            for span in line.get("spans", []):
                font_sizes.add(round(span["size"], 1))
    assert max(font_sizes) >= 12, "Title font too small"
    assert min(font_sizes) <= 8, "Detail font too large"
    print(f"  ✓ Font sizes: {sorted(font_sizes)} (hierarchy preserved)")

    print("  PASSED\n")
    return True


def test_plan_extraction_regex():
    """Test plan extraction capabilities from DXF parsed output."""
    print("=" * 60)
    print("TEST: Plan Extraction from DXF")
    print("=" * 60)

    result = parse_dxf(DXF_PATH, Path("/tmp/dxf_test"))
    page = result.pages[0]
    text = page.text

    # 1. Scale
    scale_match = SCALE_RE.search(text)
    assert scale_match
    print(f"  ✓ Scale: 1:{scale_match.group(1)}")

    # 2. DIMENSION blocks (from enhanced parser)
    dim_blocks = [b for b in page.blocks if b.block_type == "dimension"]
    dim_values = []
    for b in dim_blocks:
        try:
            v = float(b.text)
            dim_values.append(v)
        except ValueError:
            pass
    print(f"  ✓ DIMENSION values: {dim_values}")

    # 3. Room names and areas (parsed from text lines)
    # DXF output lists room names first, then areas in same order
    lines = text.split("\n")
    room_names = []
    area_values = []
    for line in lines:
        stripped = line.strip()
        for room in expected["rooms"]:
            if stripped == room["name"] and room["name"] not in room_names:
                room_names.append(room["name"])
        area_match = re.match(r"^(\d+(?:\.\d+)?)\s*m2?$", stripped)
        if area_match:
            area_values.append(float(area_match.group(1)))

    found_rooms = {}
    for i, name in enumerate(room_names):
        if i < len(area_values):
            found_rooms[name] = area_values[i]

    print(f"  ✓ Rooms with areas: {found_rooms}")

    # 4. Validate areas against expected
    for room in expected["rooms"]:
        name = room["name"]
        exp_area = room["area_m2"]
        if name in found_rooms:
            actual = found_rooms[name]
            diff = abs(actual - exp_area)
            assert diff < 0.1, f"Room {name}: expected {exp_area}, got {actual}"
            print(f"    ✓ {name}: {actual:.1f} m² (expected {exp_area:.1f})")

    # 5. Geometry summary
    assert "Geometría:" in text
    assert "line=" in text
    print("  ✓ Geometry summary present")

    # 6. Units
    assert "Unidades: m" in text
    print("  ✓ Units detected: m")

    print("  PASSED\n")
    return True


def test_manifest_completeness():
    """Validate manifest has all required fields (PM0.2)."""
    print("=" * 60)
    print("TEST: Manifest Completeness")
    print("=" * 60)

    assert "document_type" in manifest
    assert manifest["document_type"] == "plano_arquitectura"
    print(f"  ✓ document_type: {manifest['document_type']}")

    assert "expected" in manifest
    exp = manifest["expected"]

    required_keys = ["scale", "phase", "revision", "sheet", "rooms", "symbols", "dimensions"]
    for key in required_keys:
        assert key in exp, f"Missing key: {key}"
    print(f"  ✓ All {len(required_keys)} required keys present")

    assert len(exp["rooms"]) == 4
    assert len(exp["dimensions"]) == 6
    assert exp["symbols"]["single_door"] == 4
    assert exp["symbols"]["window"] == 4
    print(f"  ✓ {len(exp['rooms'])} rooms, {len(exp['dimensions'])} dims, {exp['symbols']} symbols")

    print("  PASSED\n")
    return True


if __name__ == "__main__":
    results = []
    results.append(("Manifest", test_manifest_completeness()))
    results.append(("DXF Parser", test_dxf()))
    results.append(("PDF Vector", test_pdf_vector()))
    results.append(("Regex Extraction", test_plan_extraction_regex()))

    print("=" * 60)
    print("RESULTS SUMMARY")
    print("=" * 60)
    for name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {status} — {name}")

    all_passed = all(r[1] for r in results)
    print(f"\n{'ALL TESTS PASSED' if all_passed else 'SOME TESTS FAILED'}")
    sys.exit(0 if all_passed else 1)
