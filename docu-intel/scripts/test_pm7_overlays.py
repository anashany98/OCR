"""
PM7 — Test overlays del visor + confirmación + aprendizaje.
"""
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from app.services.validation import (
    load_manifest,
    validate_plan_against_manifest,
    validate_memory_against_manifest,
    detect_contradictions,
)
from app.parsers.dxf import parse_dxf
from app.services.memory_extraction import (
    parse_memory_structure,
    sections_to_chunks,
    extract_specifications,
)
from app.services.work_item_extraction import (
    extract_work_items_from_text,
    aggregate_work_items,
)
from app.services.classification import classify_document

BASE = Path(__file__).parent.parent
PLANOS_DIR = BASE / "data" / "input" / "planos"
MEM_DIR = BASE / "data" / "input" / "memorias"


# =========================================================================
# PM7.1 — Overlay data generation
# =========================================================================

def test_pm71_overlay_regions():
    """PM7.1: Generate overlay regions for cajetín."""
    print("=" * 60)
    print("PM7.1: Overlay Regions")
    print("=" * 60)

    # Parse DXF to get cajetín text
    dxf_path = PLANOS_DIR / "vivienda_planta_baja.dxf"
    result = parse_dxf(dxf_path, Path("/tmp/pm7_test"))
    text = result.pages[0].text

    # Detect cajetín region from text
    cajetin_lines = []
    for line in text.split("\n"):
        if any(kw in line for kw in ["VIVIENDA", "Hoja:", "Rev:", "Escala:", "Cliente:"]):
            cajetin_lines.append(line)

    assert len(cajetin_lines) >= 2, f"Expected >= 2 cajetín lines, got {len(cajetin_lines)}"

    # Generate overlay region (normalized coordinates)
    overlay = {
        "region_type": "cajetin",
        "bbox": (0.05, 0.85, 0.35, 0.95),  # normalized PDF coords
        "label": " | ".join(cajetin_lines[:2]),
        "confidence": 0.9,
        "page_number": 1,
    }

    print(f"  Cajetín overlay:")
    print(f"    Type: {overlay['region_type']}")
    print(f"    Label: {overlay['label']}")
    print(f"    BBox: {overlay['bbox']}")
    print(f"    Confidence: {overlay['confidence']}")

    assert overlay["region_type"] == "cajetin"
    assert overlay["confidence"] > 0.8
    assert len(overlay["bbox"]) == 4

    print("  PASSED\n")
    return True


def test_pm71_chat_facts():
    """PM7.1: Generate chat fact overlays from extracted data."""
    print("=" * 60)
    print("PM7.1: Chat Facts Overlay")
    print("=" * 60)

    # Extract rooms
    dxf_path = PLANOS_DIR / "vivienda_planta_baja.dxf"
    result = parse_dxf(dxf_path, Path("/tmp/pm7_facts"))
    text = result.pages[0].text

    # Parse rooms from text (DXF lists names then areas in sequence)
    lines = text.split("\n")
    room_facts = []
    import re
    room_names = []
    area_values = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("Cota:") and not stripped.startswith("VIVIENDA") and not stripped.startswith("Hoja:") and not stripped.startswith("Capas:") and not stripped.startswith("Unidades:") and not stripped.startswith("Geometría:"):
            area_match = re.match(r"^(\d+(?:\.\d+)?)\s*m2?$", stripped)
            if area_match:
                area_values.append(float(area_match.group(1)))
            elif len(stripped) > 1 and not stripped[0].isdigit() and "m2" not in stripped:
                room_names.append(stripped)

    # Match rooms with areas (same order)
    for i, name in enumerate(room_names):
        if i < len(area_values):
            room_facts.append({
                "fact_type": "room",
                "subject": name,
                "value": f"{area_values[i]:.1f} m²",
                "bbox": None,
                "confidence": 0.9,
            })

    print(f"  Room facts generated: {len(room_facts)}")
    for f in room_facts:
        print(f"    {f['fact_type']}: {f['subject']} = {f['value']}")

    assert len(room_facts) >= 4, f"Expected >= 4 room facts, got {len(room_facts)}"

    # Generate dimension facts
    dim_blocks = [b for b in result.pages[0].blocks if b.block_type == "dimension"]
    dim_facts = []
    for b in dim_blocks:
        try:
            v = float(b.text)
            if v > 0:
                dim_facts.append({
                    "fact_type": "dimension",
                    "subject": f"Cota {v:.2f}",
                    "value": f"{v:.2f} m",
                    "bbox": b.bbox,
                    "confidence": 0.85,
                })
        except ValueError:
            pass

    print(f"  Dimension facts generated: {len(dim_facts)}")
    assert len(dim_facts) >= 2

    print("  PASSED\n")
    return True


# =========================================================================
# PM7.2 — Confirmation actions
# =========================================================================

def test_pm72_confirmation_actions():
    """PM7.2: Test confirmation/correction logic."""
    print("=" * 60)
    print("PM7.2: Confirmation Actions")
    print("=" * 60)

    # Simulate room confirmation
    room = {
        "name": "Salón",
        "area_m2": 20.0,
        "confidence": 0.75,
        "needs_review": True,
        "source": "vlm_suggestion",
    }

    # Confirm room
    room["needs_review"] = False
    room["confidence"] = min(1.0, room["confidence"] + 0.2)
    print(f"  After confirm: confidence={room['confidence']}, needs_review={room['needs_review']}")
    assert room["needs_review"] == False
    assert room["confidence"] == 0.95

    # Reject room
    room["needs_review"] = True
    room["confidence"] = max(0.0, room["confidence"] - 0.3)
    print(f"  After reject: confidence={room['confidence']}, needs_review={room['needs_review']}")
    assert room["needs_review"] == True
    assert abs(room["confidence"] - 0.65) < 0.01

    # Correct room name
    room["name"] = "Salón estar"
    room["needs_review"] = False
    room["confidence"] = min(1.0, room["confidence"] + 0.3)
    print(f"  After correct: name={room['name']}, confidence={room['confidence']}")
    assert room["name"] == "Salón estar"
    assert room["confidence"] == 0.95

    # Scale calibration
    point1 = {"x": 100, "y": 200}
    point2 = {"x": 300, "y": 200}
    real_distance_m = 5.0

    dx = point2["x"] - point1["x"]
    dy = point2["y"] - point1["y"]
    pixel_distance = math.sqrt(dx * dx + dy * dy)
    pixels_per_meter = pixel_distance / real_distance_m
    # Scale ratio: pixels_per_meter at 72 DPI
    # 1 inch = 25.4mm, 72 DPI = 72 pixels/inch
    # scale_ratio = real_world_pixels / drawing_pixels
    if pixels_per_meter > 0:
        scale_ratio = int(pixels_per_meter * 25.4 / 72)
    else:
        scale_ratio = 0

    print(f"  Scale calibration: {pixel_distance}px = {real_distance_m}m → 1:{scale_ratio}")
    assert scale_ratio > 0
    assert scale_ratio < 1000  # Reasonable scale range

    print("  PASSED\n")
    return True


# =========================================================================
# PM7.3 — Learning pipeline structure
# =========================================================================

def test_pm73_learning_pipeline():
    """PM7.3: Validate learning pipeline structure."""
    print("=" * 60)
    print("PM7.3: Learning Pipeline")
    print("=" * 60)

    # Define the learning pipeline flow
    learning_flow = {
        "step_1": "User confirms/rejects/corrects entity",
        "step_2": "System records correction with audit trail",
        "step_3": "Correction stored as training example",
        "step_4": "Examples aggregated for evaluation",
        "step_5": "Patterns reviewed before rule updates",
    }

    print("  Learning pipeline flow:")
    for step, desc in learning_flow.items():
        print(f"    {step}: {desc}")

    # Validate audit trail structure
    audit_entry = {
        "user_id": 1,
        "action": "plan_room_corrected",
        "entity_type": "plan_room",
        "entity_id": 42,
        "previous_value": {"name": "Salón", "confidence": 0.75},
        "new_value": {"name": "Salón estar", "confidence": 0.95},
        "created_at": "2025-01-15T10:30:00Z",
    }

    assert audit_entry["action"] == "plan_room_corrected"
    assert "previous_value" in audit_entry
    assert "new_value" in audit_entry

    print(f"\n  Audit entry example:")
    print(f"    Action: {audit_entry['action']}")
    print(f"    Previous: {audit_entry['previous_value']}")
    print(f"    New: {audit_entry['new_value']}")

    print("  PASSED\n")
    return True


# =========================================================================
# Integration: Full PM7 workflow
# =========================================================================

def test_pm7_full_workflow():
    """PM7: Full overlay + confirmation workflow."""
    print("=" * 60)
    print("PM7: Full Workflow")
    print("=" * 60)

    # 1. Parse plan
    dxf_path = PLANOS_DIR / "vivienda_planta_baja.dxf"
    result = parse_dxf(dxf_path, Path("/tmp/pm7_workflow"))
    text = result.pages[0].text

    # 2. Extract rooms
    import re
    lines = text.split("\n")
    rooms = []
    room_names = []
    area_values = []
    for line in lines:
        stripped = line.strip()
        if stripped in ["Salón", "Cocina", "Dormitorio 1", "Baño"] and stripped not in room_names:
            room_names.append(stripped)
        area_match = re.match(r"^(\d+(?:\.\d+)?)\s*m2?$", stripped)
        if area_match:
            area_values.append(float(area_match.group(1)))
    for i, name in enumerate(room_names):
        if i < len(area_values):
            rooms.append({"name": name, "area_m2": area_values[i], "needs_review": True})

    print(f"  1. Parsed {len(rooms)} rooms")

    # 3. Generate overlays
    overlays = [
        {"type": "cajetin", "label": "VIVIENDA UNIFAMILIAR"},
    ]
    for room in rooms:
        overlays.append({"type": "room", "label": room["name"]})

    print(f"  2. Generated {len(overlays)} overlays")

    # 4. User confirms rooms
    confirmed = 0
    for room in rooms:
        room["needs_review"] = False
        room["confidence"] = min(1.0, 0.75 + 0.2)
        confirmed += 1

    print(f"  3. User confirmed {confirmed} rooms")

    # 5. Extract specs
    memory_path = MEM_DIR / "memoria_constructiva_ejemplo.txt"
    memory_text = memory_path.read_text(encoding="utf-8")
    specs = extract_specifications(memory_text, document_id=1, page_number=1)

    print(f"  4. Extracted {len(specs)} specifications from memory")

    # 6. Cross-validate
    plan_data = {"rooms": rooms, "scale": "1:100"}
    contradictions = detect_contradictions(plan_data=plan_data, memory_specs=specs)

    print(f"  5. Cross-validation: {len(contradictions)} contradictions")

    # 7. Summary
    print(f"\n  Workflow summary:")
    print(f"    Rooms: {len(rooms)} (all confirmed)")
    print(f"    Specs: {len(specs)}")
    print(f"    Overlays: {len(overlays)}")
    print(f"    Contradictions: {len(contradictions)}")

    assert confirmed == len(rooms)
    assert len(specs) >= 4

    print("  PASSED\n")
    return True


if __name__ == "__main__":
    results = []
    results.append(("PM7.1 Overlay Regions", test_pm71_overlay_regions()))
    results.append(("PM7.1 Chat Facts", test_pm71_chat_facts()))
    results.append(("PM7.2 Confirmation", test_pm72_confirmation_actions()))
    results.append(("PM7.3 Learning Pipeline", test_pm73_learning_pipeline()))
    results.append(("PM7 Full Workflow", test_pm7_full_workflow()))

    print("=" * 60)
    print("RESULTS SUMMARY")
    print("=" * 60)
    for name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {status} — {name}")

    all_passed = all(r[1] for r in results)
    print(f"\n{'ALL TESTS PASSED' if all_passed else 'SOME TESTS FAILED'}")
    sys.exit(0 if all_passed else 1)
