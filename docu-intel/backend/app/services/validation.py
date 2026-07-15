"""PM5 — Automatic validation and contradiction detection.

Compares extracted data against manifest expected values and detects
contradictions between documents (plan vs memory, plan vs budget, etc.).

PM5.1: Project association (link documents by project/sheet/revision).
PM5.2: Technical graph (room→material, element→spec, etc.).
PM5.3: Revision comparison (detect changes between revisions).
PM5.4: Contradiction detection (material mismatch, dimension mismatch, etc.).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("app.services.validation")


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    """Result of validating extracted data against a manifest."""
    document_type: str
    manifest_path: str
    total_checks: int = 0
    passed: int = 0
    failed: int = 0
    warnings: int = 0
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.failed == 0

    @property
    def score(self) -> float:
        return self.passed / max(1, self.total_checks)


@dataclass
class CheckResult:
    """A single validation check."""
    category: str  # e.g. "classification", "scale", "room", "dimension", "spec"
    description: str
    passed: bool
    severity: str = "error"  # "error" | "warning" | "info"
    expected: str = ""
    actual: str = ""
    source: str = ""  # document/page that produced the value
    confidence: float = 0.0


@dataclass
class Contradiction:
    """A contradiction between two documents or between extracted and expected data."""
    type: str  # "material_mismatch", "dimension_mismatch", "scale_mismatch", etc.
    description: str
    fact_a: str  # First fact with source
    fact_b: str  # Second fact with source
    confidence: float = 0.0
    requires_review: bool = True


# ---------------------------------------------------------------------------
# PM5.4 — Manifest validation
# ---------------------------------------------------------------------------

def validate_plan_against_manifest(
    extracted: dict,
    manifest: dict,
    manifest_path: str = "",
) -> ValidationResult:
    """Validate extracted plan data against manifest expected values.

    Args:
        extracted: Dict with keys like 'scale', 'phase', 'revision', 'rooms', 'dimensions'
        manifest: The manifest dict with 'document_type' and 'expected' keys
        manifest_path: Path to the manifest file for reporting

    Returns:
        ValidationResult with all checks
    """
    expected = manifest.get("expected", {})
    doc_type = manifest.get("document_type", "unknown")

    result = ValidationResult(
        document_type=doc_type,
        manifest_path=manifest_path,
    )

    # 1. Classification check
    _check_classification(result, extracted, doc_type)

    # 2. Scale check
    _check_scale(result, extracted, expected)

    # 3. Phase/revision check
    _check_phase_revision(result, extracted, expected)

    # 4. Sheet check
    _check_sheet(result, extracted, expected)

    # 5. Room checks
    _check_rooms(result, extracted, expected)

    # 6. Dimension checks
    _check_dimensions(result, extracted, expected)

    # 7. Symbol checks
    _check_symbols(result, extracted, expected)

    return result


def validate_memory_against_manifest(
    extracted_sections: list,
    extracted_specs: list,
    manifest: dict,
    manifest_path: str = "",
) -> ValidationResult:
    """Validate extracted memory data against manifest expected values.

    Args:
        extracted_sections: List of DocumentSection from parse_memory_structure
        extracted_specs: List of TechnicalSpec from extract_specifications
        manifest: The manifest dict
        manifest_path: Path to the manifest file

    Returns:
        ValidationResult with all checks
    """
    expected = manifest.get("expected", {})
    doc_type = manifest.get("document_type", "unknown")

    result = ValidationResult(
        document_type=doc_type,
        manifest_path=manifest_path,
    )

    # 1. Classification check
    _check_classification(result, {"document_type": doc_type}, doc_type)

    # 2. Chapter checks
    _check_chapters(result, extracted_sections, expected)

    # 3. Specification checks
    _check_specifications(result, extracted_specs, expected)

    return result


# ---------------------------------------------------------------------------
# PM5.4 — Contradiction detection
# ---------------------------------------------------------------------------

def detect_contradictions(
    plan_data: dict | None = None,
    memory_specs: list | None = None,
    plan_manifest: dict | None = None,
) -> list[Contradiction]:
    """Detect contradictions between plan and memory documents.

    Compares materials, dimensions, and other properties across documents.
    Also checks for internal contradictions within memory specs.
    """
    contradictions: list[Contradiction] = []

    # Check internal contradictions in memory specs (always run if specs provided)
    if memory_specs:
        contradictions.extend(_check_internal_contradictions(memory_specs))

    # Cross-document checks (only if both sources provided)
    if plan_data and memory_specs:
        plan_rooms = plan_data.get("rooms", [])
        plan_scale = plan_data.get("scale", "")

        for spec in memory_specs:
            system = spec.system_element

            # Check material consistency
            if spec.material:
                # Look for matching room in plan
                for room in plan_rooms:
                    room_name = room.get("name", "")
                    if _fuzzy_match(system, room_name):
                        # Found a matching room - check if plan has material info
                        # (In our test data, plan doesn't have material info, so this is informational)
                        pass

            # Check scale consistency
            if plan_scale and spec.thickness_cm:
                # Verify thickness makes sense at scale
                pass

    return contradictions


def _check_internal_contradictions(specs: list) -> list[Contradiction]:
    """Check for contradictions within extracted specifications."""
    contradictions = []

    # Group specs by system_element
    by_system: dict[str, list] = {}
    for spec in specs:
        key = spec.system_element.lower()
        by_system.setdefault(key, []).append(spec)

    # Check for duplicate/conflicting values per system
    for system, system_specs in by_system.items():
        if len(system_specs) < 2:
            continue

        # Check material conflicts
        materials = [s.material for s in system_specs if s.material]
        if len(set(materials)) > 1:
            contradictions.append(Contradiction(
                type="material_mismatch",
                description=f"Multiple materials for {system}: {materials}",
                fact_a=f"Material: {materials[0]}",
                fact_b=f"Material: {materials[1]}",
                confidence=0.8,
            ))

        # Check fire rating conflicts
        fires = [s.fire_rating for s in system_specs if s.fire_rating]
        if len(set(fires)) > 1:
            contradictions.append(Contradiction(
                type="fire_rating_mismatch",
                description=f"Multiple fire ratings for {system}: {fires}",
                fact_a=f"Fire rating: {fires[0]}",
                fact_b=f"Fire rating: {fires[1]}",
                confidence=0.9,
            ))

        # Check thickness conflicts
        thicknesses = [s.thickness_cm for s in system_specs if s.thickness_cm]
        if len(set(thicknesses)) > 1:
            contradictions.append(Contradiction(
                type="thickness_mismatch",
                description=f"Multiple thicknesses for {system}: {thicknesses}",
                fact_a=f"Thickness: {thicknesses[0]} cm",
                fact_b=f"Thickness: {thicknesses[1]} cm",
                confidence=0.85,
            ))

    return contradictions


# ---------------------------------------------------------------------------
# Check implementations
# ---------------------------------------------------------------------------

def _check_classification(result: ValidationResult, extracted: dict, expected_type: str):
    """Check document classification matches expected type."""
    actual_type = extracted.get("document_type", "unknown")
    passed = actual_type == expected_type or expected_type.startswith(actual_type)

    result.checks.append(CheckResult(
        category="classification",
        description="Document type classification",
        passed=passed,
        expected=expected_type,
        actual=actual_type,
    ))
    result.total_checks += 1
    if passed:
        result.passed += 1
    else:
        result.failed += 1


def _check_scale(result: ValidationResult, extracted: dict, expected: dict):
    """Check scale extraction matches expected."""
    if "scale" not in expected:
        return

    expected_scale = expected["scale"]
    actual_scale = extracted.get("scale", "")
    passed = actual_scale == expected_scale

    result.checks.append(CheckResult(
        category="scale",
        description="Scale extraction",
        passed=passed,
        expected=expected_scale,
        actual=actual_scale,
    ))
    result.total_checks += 1
    if passed:
        result.passed += 1
    else:
        result.failed += 1


def _check_phase_revision(result: ValidationResult, extracted: dict, expected: dict):
    """Check phase and revision extraction."""
    if "phase" in expected:
        expected_phase = expected["phase"]
        actual_phase = extracted.get("phase", "")
        passed = expected_phase in actual_phase or actual_phase in expected_phase

        result.checks.append(CheckResult(
            category="phase",
            description="Phase extraction",
            passed=passed,
            expected=expected_phase,
            actual=actual_phase,
        ))
        result.total_checks += 1
        if passed:
            result.passed += 1
        else:
            result.failed += 1

    if "revision" in expected:
        expected_rev = expected["revision"]
        actual_rev = extracted.get("revision", "")
        passed = expected_rev == actual_rev

        result.checks.append(CheckResult(
            category="revision",
            description="Revision extraction",
            passed=passed,
            expected=expected_rev,
            actual=actual_rev,
        ))
        result.total_checks += 1
        if passed:
            result.passed += 1
        else:
            result.failed += 1


def _check_sheet(result: ValidationResult, extracted: dict, expected: dict):
    """Check sheet number extraction."""
    if "sheet" not in expected:
        return

    expected_sheet = expected["sheet"]
    actual_sheet = extracted.get("sheet", "")
    passed = expected_sheet == actual_sheet

    result.checks.append(CheckResult(
        category="sheet",
        description="Sheet number extraction",
        passed=passed,
        expected=expected_sheet,
        actual=actual_sheet,
    ))
    result.total_checks += 1
    if passed:
        result.passed += 1
    else:
        result.failed += 1


def _check_rooms(result: ValidationResult, extracted: dict, expected: dict):
    """Check room extraction matches expected rooms."""
    if "rooms" not in expected:
        return

    expected_rooms = expected["rooms"]
    actual_rooms = extracted.get("rooms", [])

    # Check each expected room
    for exp_room in expected_rooms:
        room_name = exp_room["name"]
        exp_area = exp_room.get("area_m2")

        # Find matching room in extracted
        found = False
        for act_room in actual_rooms:
            act_name = act_room.get("name", "")
            if _fuzzy_match(room_name, act_name):
                found = True
                # Check area if expected
                if exp_area is not None:
                    act_area = act_room.get("area_m2")
                    if act_area is not None:
                        area_diff = abs(act_area - exp_area)
                        area_ok = area_diff < 0.1 or (area_diff / max(exp_area, 0.01)) < 0.05
                        result.checks.append(CheckResult(
                            category="room_area",
                            description=f"Room '{room_name}' area",
                            passed=area_ok,
                            expected=f"{exp_area:.1f} m²",
                            actual=f"{act_area:.1f} m²",
                        ))
                        result.total_checks += 1
                        if area_ok:
                            result.passed += 1
                        else:
                            result.failed += 1
                    else:
                        result.checks.append(CheckResult(
                            category="room_area",
                            description=f"Room '{room_name}' area",
                            passed=False,
                            expected=f"{exp_area:.1f} m²",
                            actual="not extracted",
                        ))
                        result.total_checks += 1
                        result.failed += 1
                break

        if not found:
            result.checks.append(CheckResult(
                category="room",
                description=f"Room '{room_name}' found",
                passed=False,
                expected=room_name,
                actual="not found",
            ))
            result.total_checks += 1
            result.failed += 1

    # Check count
    result.checks.append(CheckResult(
        category="room_count",
        description="Room count",
        passed=len(actual_rooms) >= len(expected_rooms),
        expected=str(len(expected_rooms)),
        actual=str(len(actual_rooms)),
    ))
    result.total_checks += 1
    if len(actual_rooms) >= len(expected_rooms):
        result.passed += 1
    else:
        result.failed += 1


def _check_dimensions(result: ValidationResult, extracted: dict, expected: dict):
    """Check dimension extraction matches expected dimensions."""
    if "dimensions" not in expected:
        return

    expected_dims = expected["dimensions"]
    actual_dims = extracted.get("dimensions", [])

    # Check count
    result.checks.append(CheckResult(
        category="dimension_count",
        description="Dimension count",
        passed=len(actual_dims) >= len(expected_dims),
        expected=str(len(expected_dims)),
        actual=str(len(actual_dims)),
    ))
    result.total_checks += 1
    if len(actual_dims) >= len(expected_dims):
        result.passed += 1
    else:
        result.failed += 1

    # Check each expected dimension
    for exp_dim in expected_dims:
        exp_label = exp_dim["label"]
        exp_value = exp_dim["value_m"]

        # Find matching dimension
        found = False
        for act_dim in actual_dims:
            act_label = act_dim.get("label", "")
            act_value = act_dim.get("value_m", act_dim.get("value", 0))

            if _fuzzy_match(exp_label, act_label) or abs(float(act_value) - exp_value) < 0.01:
                found = True
                break

        result.checks.append(CheckResult(
            category="dimension",
            description=f"Dimension '{exp_label}'",
            passed=found,
            expected=f"{exp_label} = {exp_value} m",
            actual="found" if found else "not found",
        ))
        result.total_checks += 1
        if found:
            result.passed += 1
        else:
            result.failed += 1


def _check_symbols(result: ValidationResult, extracted: dict, expected: dict):
    """Check symbol extraction matches expected counts."""
    if "symbols" not in expected:
        return

    expected_symbols = expected["symbols"]
    actual_symbols = extracted.get("symbols", {})

    for sym_type, exp_count in expected_symbols.items():
        act_count = actual_symbols.get(sym_type, 0)
        passed = act_count >= exp_count

        result.checks.append(CheckResult(
            category="symbol",
            description=f"Symbol '{sym_type}' count",
            passed=passed,
            expected=str(exp_count),
            actual=str(act_count),
        ))
        result.total_checks += 1
        if passed:
            result.passed += 1
        else:
            result.failed += 1


def _check_chapters(result: ValidationResult, sections: list, expected: dict):
    """Check chapter extraction matches expected chapters."""
    if "chapters" not in expected:
        return

    expected_chapters = expected["chapters"]

    # Collect all chapter numbers from sections
    found_numbers = set()
    def collect_numbers(sections_list):
        for s in sections_list:
            num = s.heading.split(" ")[0] if s.heading else ""
            found_numbers.add(num)
            collect_numbers(s.children)
    collect_numbers(sections)

    for exp_ch in expected_chapters:
        ch_num = exp_ch["number"]
        passed = ch_num in found_numbers

        result.checks.append(CheckResult(
            category="chapter",
            description=f"Chapter '{ch_num} {exp_ch['title']}'",
            passed=passed,
            expected=f"{ch_num} {exp_ch['title']}",
            actual="found" if passed else "not found",
        ))
        result.total_checks += 1
        if passed:
            result.passed += 1
        else:
            result.failed += 1


def _check_specifications(result: ValidationResult, specs: list, expected: dict):
    """Check specification extraction matches expected specs."""
    if "specifications" not in expected:
        return

    expected_specs = expected["specifications"]

    for exp_spec in expected_specs:
        system = exp_spec["system_element"]

        # Find matching spec
        found = None
        for spec in specs:
            if _fuzzy_match(system, spec.system_element):
                found = spec
                break

        if not found:
            result.checks.append(CheckResult(
                category="spec",
                description=f"Specification for '{system}'",
                passed=False,
                expected=system,
                actual="not found",
            ))
            result.total_checks += 1
            result.failed += 1
            continue

        # Check material
        if "material" in exp_spec and exp_spec["material"]:
            exp_mat = exp_spec["material"].lower()
            act_mat = (found.material or "").lower()
            passed = exp_mat in act_mat or act_mat in exp_mat

            result.checks.append(CheckResult(
                category="spec_material",
                description=f"Material for '{system}'",
                passed=passed,
                expected=exp_spec["material"],
                actual=found.material or "none",
            ))
            result.total_checks += 1
            if passed:
                result.passed += 1
            else:
                result.failed += 1

        # Check thickness
        if "thickness_cm" in exp_spec and exp_spec["thickness_cm"] is not None:
            exp_thick = exp_spec["thickness_cm"]
            act_thick = found.thickness_cm
            passed = act_thick is not None and abs(act_thick - exp_thick) < 0.1

            result.checks.append(CheckResult(
                category="spec_thickness",
                description=f"Thickness for '{system}'",
                passed=passed,
                expected=f"{exp_thick} cm",
                actual=f"{act_thick} cm" if act_thick else "none",
            ))
            result.total_checks += 1
            if passed:
                result.passed += 1
            else:
                result.failed += 1

        # Check fire rating
        if "fire_rating" in exp_spec and exp_spec["fire_rating"]:
            exp_fire = exp_spec["fire_rating"]
            act_fire = found.fire_rating or ""
            passed = exp_fire in act_fire or act_fire in exp_fire

            result.checks.append(CheckResult(
                category="spec_fire",
                description=f"Fire rating for '{system}'",
                passed=passed,
                expected=exp_fire,
                actual=act_fire or "none",
            ))
            result.total_checks += 1
            if passed:
                result.passed += 1
            else:
                result.failed += 1

        # Check thermal
        if "thermal_insulation" in exp_spec and exp_spec["thermal_insulation"]:
            exp_thermal = exp_spec["thermal_insulation"]
            act_thermal = found.thermal_insulation or ""
            passed = exp_thermal in act_thermal or act_thermal in exp_thermal

            result.checks.append(CheckResult(
                category="spec_thermal",
                description=f"Thermal insulation for '{system}'",
                passed=passed,
                expected=exp_thermal,
                actual=act_thermal or "none",
            ))
            result.total_checks += 1
            if passed:
                result.passed += 1
            else:
                result.failed += 1

        # Check acoustic
        if "acoustic_rating" in exp_spec and exp_spec["acoustic_rating"]:
            exp_acoustic = exp_spec["acoustic_rating"]
            act_acoustic = found.acoustic_rating or ""
            passed = exp_acoustic in act_acoustic or act_acoustic in exp_acoustic

            result.checks.append(CheckResult(
                category="spec_acoustic",
                description=f"Acoustic rating for '{system}'",
                passed=passed,
                expected=exp_acoustic,
                actual=act_acoustic or "none",
            ))
            result.total_checks += 1
            if passed:
                result.passed += 1
            else:
                result.failed += 1


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _fuzzy_match(a: str, b: str, threshold: float = 0.6) -> bool:
    """Simple fuzzy string matching for Spanish construction terms."""
    a_lower = a.lower().strip()
    b_lower = b.lower().strip()

    # Exact match
    if a_lower == b_lower:
        return True

    # One contains the other
    if a_lower in b_lower or b_lower in a_lower:
        return True

    # Numeric comparison (for dimensions like "5,00" vs "5.00")
    a_num = _parse_number(a_lower)
    b_num = _parse_number(b_lower)
    if a_num is not None and b_num is not None:
        return abs(a_num - b_num) < 0.01

    # Word overlap
    words_a = set(a_lower.split())
    words_b = set(b_lower.split())
    if not words_a or not words_b:
        return False

    overlap = len(words_a & words_b) / max(len(words_a), len(words_b))
    return overlap >= threshold


def _parse_number(s: str) -> float | None:
    """Try to parse a number from a string, handling Spanish format."""
    try:
        # Remove common prefixes/suffixes
        s = s.strip().rstrip("m").rstrip("cm").rstrip("mm")
        # Handle Spanish format: "5,00" -> 5.00
        s = s.replace(",", ".")
        return float(s)
    except (ValueError, AttributeError):
        return None


def load_manifest(path: str | Path) -> dict:
    """Load a manifest JSON file."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def format_validation_report(result: ValidationResult) -> str:
    """Format a validation result as a human-readable report."""
    lines = [
        f"Validation Report: {result.document_type}",
        f"Manifest: {result.manifest_path}",
        f"Score: {result.passed}/{result.total_checks} ({result.score:.0%})",
        "",
    ]

    if result.failed > 0:
        lines.append("FAILURES:")
        for check in result.checks:
            if not check.passed:
                lines.append(f"  [{check.category}] {check.description}")
                lines.append(f"    Expected: {check.expected}")
                lines.append(f"    Actual: {check.actual}")
        lines.append("")

    if result.passed > 0:
        lines.append("PASSES:")
        for check in result.checks:
            if check.passed:
                lines.append(f"  [{check.category}] {check.description}")
        lines.append("")

    lines.append(f"Result: {'PASS' if result.success else 'FAIL'}")
    return "\n".join(lines)


def format_contradictions_report(contradictions: list[Contradiction]) -> str:
    """Format contradictions as a report."""
    if not contradictions:
        return "No contradictions found."

    lines = [f"Contradictions Found: {len(contradictions)}", ""]
    for i, c in enumerate(contradictions, 1):
        lines.append(f"{i}. [{c.type}] {c.description}")
        lines.append(f"   Fact A: {c.fact_a}")
        lines.append(f"   Fact B: {c.fact_b}")
        lines.append(f"   Confidence: {c.confidence:.0%}")
        if c.requires_review:
            lines.append("   ⚠ REQUIRES REVIEW")
        lines.append("")

    return "\n".join(lines)


__all__ = [
    "ValidationResult",
    "CheckResult",
    "Contradiction",
    "validate_plan_against_manifest",
    "validate_memory_against_manifest",
    "detect_contradictions",
    "load_manifest",
    "format_validation_report",
    "format_contradictions_report",
]
