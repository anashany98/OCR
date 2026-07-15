"""
PM4.1/PM4.2 — Test integral de parsing de memorias y extracción de especificaciones.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from app.services.memory_extraction import (
    parse_memory_structure,
    sections_to_chunks,
    extract_specifications,
)

BASE = Path(__file__).parent.parent
MEM_DIR = BASE / "data" / "input" / "memorias"
MEMORY_PATH = MEM_DIR / "memoria_constructiva_ejemplo.txt"
MANIFEST_PATH = MEM_DIR / "memoria_constructiva_ejemplo.manifest.json"


def test_pm41_structure_parsing():
    """PM4.1: Test hierarchical structure parsing."""
    print("=" * 60)
    print("PM4.1: Structure Parsing")
    print("=" * 60)

    text = MEMORY_PATH.read_text(encoding="utf-8")
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        manifest = json.load(f)
    expected = manifest["expected"]

    # Parse structure
    sections = parse_memory_structure(text, document_type="memoria_constructiva")

    # Validate chapters found
    all_chapters = []
    def collect_chapters(sections_list, depth=0):
        for s in sections_list:
            num = s.heading.split(" ")[0] if s.heading else ""
            all_chapters.append({"number": num, "title": s.heading, "level": s.level})
            collect_chapters(s.children, depth + 1)

    collect_chapters(sections)

    print(f"  Sections found: {len(all_chapters)}")
    for ch in all_chapters:
        indent = "  " * (ch["level"] - 1)
        print(f"    {indent}{ch['number']} (level {ch['level']})")

    # Check expected chapters exist
    expected_chapters = expected["chapters"]
    found_numbers = {ch["number"] for ch in all_chapters}

    for exp in expected_chapters:
        found = exp["number"] in found_numbers
        status = "✓" if found else "✗"
        print(f"  {status} Chapter {exp['number']}: {exp['title']}")
        assert found, f"Chapter {exp['number']} not found"

    print(f"  ✓ All {len(expected_chapters)} chapters found")
    print("  PASSED\n")
    return True


def test_pm41_chunking():
    """PM4.1: Test structured chunking with metadata."""
    print("=" * 60)
    print("PM4.1: Structured Chunking")
    print("=" * 60)

    text = MEMORY_PATH.read_text(encoding="utf-8")
    sections = parse_memory_structure(text, document_type="memoria_constructiva")

    chunks = sections_to_chunks(
        sections,
        document_type="memoria_constructiva",
        filename="memoria_constructiva_ejemplo.txt",
        max_words=100,  # Small chunks for testing
    )

    print(f"  Chunks generated: {len(chunks)}")

    # Check chunks have hierarchical paths
    chunks_with_path = [c for c in chunks if c.chapter_path]
    print(f"  Chunks with chapter path: {len(chunks_with_path)}")
    assert len(chunks_with_path) > 0, "No chunks have chapter paths"

    # Check embedding text format
    sample = chunks_with_path[0]
    emb_text = sample.embedding_text()
    print(f"  Sample embedding text: {emb_text[:150]}...")
    assert "[documento=" in emb_text, "Missing document type in embedding"
    assert "[capítulo=" in emb_text or "capítulo=" in emb_text, "Missing chapter in embedding"

    # Check chunk types
    text_chunks = [c for c in chunks if c.chunk_type == "text"]
    table_chunks = [c for c in chunks if c.chunk_type == "table"]
    print(f"  Text chunks: {len(text_chunks)}")
    print(f"  Table chunks: {len(table_chunks)}")

    # Verify hierarchical nesting
    levels = set(c.chapter_path.count("→") for c in chunks_with_path)
    print(f"  Nesting depths: {sorted(levels)}")

    print("  PASSED\n")
    return True


def test_pm42_spec_extraction():
    """PM4.2: Test technical specification extraction."""
    print("=" * 60)
    print("PM4.2: Specification Extraction")
    print("=" * 60)

    text = MEMORY_PATH.read_text(encoding="utf-8")
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        manifest = json.load(f)
    expected = manifest["expected"]

    specs = extract_specifications(text, document_id=1, page_number=1)

    print(f"  Specifications extracted: {len(specs)}")
    for spec in specs:
        print(f"    - {spec.system_element}: material={spec.material}, "
              f"thickness={spec.thickness_cm}, fire={spec.fire_rating}, "
              f"thermal={spec.thermal_insulation}, acoustic={spec.acoustic_rating}")

    # Validate expected specifications
    for exp_spec in expected["specifications"]:
        system = exp_spec["system_element"]
        found = [s for s in specs if system.lower() in s.system_element.lower()]
        assert found, f"Specification for '{system}' not found"

        spec = found[0]
        if exp_spec.get("material"):
            assert exp_spec["material"].lower() in (spec.material or "").lower(), \
                f"Material mismatch for {system}: expected '{exp_spec['material']}', got '{spec.material}'"
            print(f"  ✓ {system}: material={spec.material}")

        if exp_spec.get("thickness_cm"):
            assert spec.thickness_cm is not None, \
                f"Thickness not found for {system}"
            print(f"  ✓ {system}: thickness={spec.thickness_cm} cm")

        if exp_spec.get("fire_rating"):
            assert spec.fire_rating, \
                f"Fire rating not found for {system}"
            print(f"  ✓ {system}: fire={spec.fire_rating}")

        if exp_spec.get("thermal_insulation"):
            assert spec.thermal_insulation, \
                f"Thermal insulation not found for {system}"
            print(f"  ✓ {system}: thermal={spec.thermal_insulation}")

        if exp_spec.get("acoustic_rating"):
            assert spec.acoustic_rating, \
                f"Acoustic rating not found for {system}"
            print(f"  ✓ {system}: acoustic={spec.acoustic_rating}")

    # Check evidence is preserved
    for spec in specs:
        assert spec.source_text, f"No source text for {spec.system_element}"
        assert spec.confidence > 0, f"Zero confidence for {spec.system_element}"
        assert spec.chapter_path, f"No chapter path for {spec.system_element}"

    print(f"  ✓ All specifications have evidence (source_text, confidence, chapter_path)")
    print("  PASSED\n")
    return True


def test_pm42_standalone_spec():
    """PM4.2: Test extraction from isolated paragraphs."""
    print("=" * 60)
    print("PM4.2: Standalone Spec Extraction")
    print("=" * 60)

    test_text = """
    Material: Pladur acústico doble capa
    Espesor: 15 cm
    Clase de fuego: REI 60
    Aislamiento acústico: Rw = 52 dB
    Aislamiento térmico: U = 0.28 W/m²K
    Norma UNE-EN 14190:2014
    """

    specs = extract_specifications(test_text, document_id=2, page_number=5)
    assert len(specs) >= 1, "No specs extracted from standalone text"

    spec = specs[0]
    print(f"  Material: {spec.material}")
    print(f"  Thickness: {spec.thickness_cm} cm")
    print(f"  Fire: {spec.fire_rating}")
    print(f"  Acoustic: {spec.acoustic_rating}")
    print(f"  Thermal: {spec.thermal_insulation}")
    print(f"  Standards: {spec.cited_standards}")
    print(f"  Confidence: {spec.confidence:.2f}")

    assert spec.material == "Pladur acústico doble capa"
    assert spec.thickness_cm == 15.0
    assert spec.fire_rating == "REI 60"
    assert spec.acoustic_rating == "Rw = 52 dB"
    assert spec.thermal_insulation == "U = 0.28 W/m²K"
    # Check for standard (may be "EN 14190:2014" or "UNE-EN 14190:2014")
    assert any("14190" in s for s in spec.cited_standards), \
        f"Expected standard containing '14190', got: {spec.cited_standards}"
    assert spec.confidence > 0.7

    print("  ✓ All standalone spec fields extracted correctly")
    print("  PASSED\n")
    return True


if __name__ == "__main__":
    results = []
    results.append(("PM4.1 Structure", test_pm41_structure_parsing()))
    results.append(("PM4.1 Chunking", test_pm41_chunking()))
    results.append(("PM4.2 Spec Extraction", test_pm42_spec_extraction()))
    results.append(("PM4.2 Standalone", test_pm42_standalone_spec()))

    print("=" * 60)
    print("RESULTS SUMMARY")
    print("=" * 60)
    for name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {status} — {name}")

    all_passed = all(r[1] for r in results)
    print(f"\n{'ALL TESTS PASSED' if all_passed else 'SOME TESTS FAILED'}")
    sys.exit(0 if all_passed else 1)
