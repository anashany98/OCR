"""
PM0.2 — Corpus de evaluación: validación de ambos planos contra manifests.
Ejecuta extracción y comparación con valores esperados.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from app.parsers.dxf import parse_dxf
from app.services.classification import classify_document

BASE = Path(__file__).parent.parent
PLANOS_DIR = BASE / "data" / "input" / "planos"

PLANS = [
    {
        "name": "Vivienda Planta Baja",
        "dxf": PLANOS_DIR / "vivienda_planta_baja.dxf",
        "manifest": PLANOS_DIR / "vivienda_planta_baja.manifest.json",
    },
    {
        "name": "Sección Constructiva",
        "dxf": PLANOS_DIR / "seccion_constructiva.dxf",
        "manifest": PLANOS_DIR / "seccion_constructiva.manifest.json",
    },
]


def validate_plan(plan_info: dict) -> dict:
    """Validate a single plan against its manifest."""
    name = plan_info["name"]
    dxf_path = plan_info["dxf"]

    with open(plan_info["manifest"], encoding="utf-8") as f:
        manifest = json.load(f)
    expected = manifest["expected"]

    print(f"\n{'=' * 60}")
    print(f"VALIDATING: {name}")
    print(f"{'=' * 60}")

    results = {"name": name, "checks": [], "passed": 0, "failed": 0}

    def check(description: str, condition: bool, detail: str = ""):
        status = "✓" if condition else "✗"
        results["checks"].append({"desc": description, "passed": condition, "detail": detail})
        if condition:
            results["passed"] += 1
        else:
            results["failed"] += 1
        print(f"  {status} {description}" + (f" — {detail}" if detail else ""))

    # 1. Classification
    result = parse_dxf(dxf_path, Path("/tmp/corpus_test"))
    page = result.pages[0]
    text = page.text

    classification = classify_document(
        filename=dxf_path.name,
        source_path=str(dxf_path),
        text=text,
    )
    check(
        "Classification matches expected type",
        classification.document_type == manifest["document_type"],
        f"got '{classification.document_type}', expected '{manifest['document_type']}'",
    )

    # 2. Scale
    scale_match = re.search(r"1\s*[:/]\s*(\d+)", text)
    if scale_match:
        scale_ratio = int(scale_match.group(1))
        expected_scale = int(expected["scale"].split(":")[1])
        check(
            "Scale extraction",
            scale_ratio == expected_scale,
            f"got 1:{scale_ratio}, expected 1:{expected_scale}",
        )
    else:
        check("Scale extraction", False, "no scale found")

    # 3. Phase/Revision (if expected)
    if "phase" in expected:
        check(
            "Phase extraction",
            expected["phase"] in text,
            f"looking for '{expected['phase']}'",
        )
    if "revision" in expected:
        check(
            "Revision extraction",
            f"Rev: {expected['revision']}" in text or f"Rev {expected['revision']}" in text,
            f"looking for revision {expected['revision']}",
        )

    # 4. Rooms (if expected)
    if "rooms" in expected:
        for room in expected["rooms"]:
            check(
                f"Room '{room['name']}' found",
                room["name"] in text,
            )

    # 5. Dimensions
    if "dimensions" in expected:
        dim_blocks = [b for b in page.blocks if b.block_type == "dimension"]
        check(
            "DIMENSION blocks extracted",
            len(dim_blocks) >= len(expected["dimensions"]),
            f"got {len(dim_blocks)}, expected >= {len(expected['dimensions'])}",
        )

    # 6. Materials (for section plan)
    if "materials" in expected:
        for mat in expected["materials"]:
            mat_name = mat["name"]
            check(
                f"Material '{mat_name}' found",
                mat_name.lower() in text.lower(),
            )

    # 7. Geometry
    check("Geometry extracted", "Geometría:" in text)
    check("Units detected", "Unidades:" in text)

    # 8. Layers
    check("Layers present", "Capas:" in text)

    return results


if __name__ == "__main__":
    all_results = []
    for plan in PLANS:
        results = validate_plan(plan)
        all_results.append(results)

    # Summary
    print(f"\n{'=' * 60}")
    print("CORPUS VALIDATION SUMMARY")
    print(f"{'=' * 60}")

    total_passed = 0
    total_failed = 0
    for r in all_results:
        total_passed += r["passed"]
        total_failed += r["failed"]
        status = "PASS" if r["failed"] == 0 else "FAIL"
        print(f"  {status} — {r['name']}: {r['passed']}/{r['passed'] + r['failed']} checks")

    print(f"\nTotal: {total_passed}/{total_passed + total_failed} checks passed")

    if total_failed > 0:
        print("\nFailed checks:")
        for r in all_results:
            for c in r["checks"]:
                if not c["passed"]:
                    print(f"  - [{r['name']}] {c['desc']}: {c['detail']}")

    sys.exit(0 if total_failed == 0 else 1)
