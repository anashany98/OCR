"""
PM9 — Test chat técnico con RAG y herramientas.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from app.services.technical_chat import (
    TECHNICAL_TOOLS,
    TOOL_SYSTEM_PROMPT,
    classify_question,
    build_search_queries,
    generate_grounded_answer,
    execute_tool,
    ChatSource,
)

BASE = Path(__file__).parent.parent


# =========================================================================
# PM9.1 — Tool definitions
# =========================================================================

def test_pm91_tool_definitions():
    """PM9.1: Validate tool definitions are complete."""
    print("=" * 60)
    print("PM9.1: Tool Definitions")
    print("=" * 60)

    assert len(TECHNICAL_TOOLS) >= 10, f"Expected >= 10 tools, got {len(TECHNICAL_TOOLS)}"

    required_tools = [
        "get_plan_info", "get_plan_rooms", "get_room_dimensions",
        "get_plan_symbols", "get_technical_specs", "find_material_by_room",
        "get_work_items", "aggregate_budget", "compare_documents",
        "search_technical_text",
    ]

    tool_names = [t["name"] for t in TECHNICAL_TOOLS]
    for name in required_tools:
        assert name in tool_names, f"Tool '{name}' not defined"
        # Validate structure
        tool = next(t for t in TECHNICAL_TOOLS if t["name"] == name)
        assert "description" in tool, f"Tool '{name}' missing description"
        assert "parameters" in tool, f"Tool '{name}' missing parameters"

    print(f"  ✓ {len(TECHNICAL_TOOLS)} tools defined")
    print(f"  ✓ All {len(required_tools)} required tools present")
    print(f"  ✓ System prompt: {len(TOOL_SYSTEM_PROMPT)} chars")

    print("  PASSED\n")
    return True


# =========================================================================
# PM9.2 — Question classification
# =========================================================================

def test_pm92_question_classification():
    """PM9.2: Classify questions into topics."""
    print("=" * 60)
    print("PM9.2: Question Classification")
    print("=" * 60)

    test_cases = [
        ("¿Cuánto mide el Salón?", ["room", "dimension"]),
        ("¿Qué material llevan los tabiques?", ["material"]),
        ("¿Qué escala tiene el plano A-01?", ["scale"]),
        ("¿Cuántas puertas hay en la cocina?", ["symbol", "room"]),
        ("¿Qué normativa se cumple?", ["standard"]),
        ("¿Cuánto cuesta el forjado?", ["budget"]),
        ("¿Qué resistencia al fuego tiene?", ["fire"]),
        ("¿Qué aislamiento acústico hay?", ["acoustic"]),
        ("¿Cuánto mide el Baño según el plano?", ["room", "dimension"]),
    ]

    for question, expected_topics in test_cases:
        topics = classify_question(question)
        found = any(t in topics for t in expected_topics)
        status = "✓" if found else "✗"
        print(f"  {status} '{question[:50]}...' → {topics}")
        assert found, f"Expected one of {expected_topics}, got {topics}"

    print("  PASSED\n")
    return True


# =========================================================================
# PM9.3 — Search query building
# =========================================================================

def test_pm93_search_queries():
    """PM9.3: Build search queries from questions."""
    print("=" * 60)
    print("PM9.3: Search Query Building")
    print("=" * 60)

    question = "¿Qué material llevan los tabiques del Dormitorio 1?"
    queries = build_search_queries(question)

    print(f"  Original: {question}")
    print(f"  Queries generated: {len(queries)}")
    for q in queries:
        print(f"    - {q}")

    assert len(queries) >= 2
    assert question in queries
    assert any("tabique" in q.lower() or "dormitorio" in q.lower() for q in queries)

    print("  PASSED\n")
    return True


# =========================================================================
# PM9.4 — Answer generation
# =========================================================================

def test_pm94_answer_generation():
    """PM9.4: Generate grounded answers."""
    print("=" * 60)
    print("PM9.4: Answer Generation")
    print("=" * 60)

    # Test with context
    context = [
        {
            "text": "El Salón tiene una superficie de 20.0 m² según el plano A-01.",
            "document_id": 1,
            "document_type": "plano_arquitectura",
            "filename": "vivienda_planta_baja.dxf",
            "page_number": 1,
            "section": "Planta Baja",
            "confidence": 0.9,
        },
        {
            "text": "Los tabiques interiores son de Pladur con espesor de 10 cm.",
            "document_id": 2,
            "document_type": "memoria_constructiva",
            "filename": "memoria_constructiva.txt",
            "page_number": 34,
            "section": "2.4 Tabiquería interior",
            "confidence": 0.85,
        },
    ]

    response = generate_grounded_answer(
        "¿Qué material y superficie tiene el Salón?",
        context_chunks=context,
    )

    print(f"  Answer length: {len(response.answer)} chars")
    print(f"  Sources: {len(response.sources)}")
    print(f"  Confidence: {response.confidence:.0%}")
    print(f"  Preview: {response.answer[:200]}...")

    assert len(response.answer) > 50
    assert len(response.sources) >= 2
    assert response.confidence > 0.3

    # Check sources have provenance
    for src in response.sources:
        assert src.document_id is not None
        assert src.filename

    # Test without context
    empty_response = generate_grounded_answer("Pregunta sin contexto", [])
    assert "No encontré" in empty_response.answer or "no dispongo" in empty_response.answer.lower()

    print("  PASSED\n")
    return True


# =========================================================================
# PM9.5 — Tool execution
# =========================================================================

def test_pm95_tool_execution():
    """PM9.5: Validate tool execution structure."""
    print("=" * 60)
    print("PM9.5: Tool Execution")
    print("=" * 60)

    # Test without DB (should return errors gracefully)
    result = execute_tool("get_plan_info", {"plan_id": 1}, db_session=None)
    assert "error" in result
    print(f"  ✓ get_plan_info (no DB): {result['error']}")

    result = execute_tool("get_plan_rooms", {"plan_id": 1}, db_session=None)
    assert "error" in result or "rooms" in result
    print(f"  ✓ get_plan_rooms (no DB): graceful")

    result = execute_tool("unknown_tool", {}, db_session=None)
    assert "error" in result
    print(f"  ✓ Unknown tool: {result['error']}")

    # Test tool dispatch
    valid_tools = ["get_plan_info", "get_plan_rooms", "get_room_dimensions",
                    "get_plan_symbols", "get_technical_specs", "find_material_by_room",
                    "get_work_items", "aggregate_budget", "compare_documents",
                    "search_technical_text"]
    for tool_name in valid_tools:
        result = execute_tool(tool_name, {}, db_session=None)
        assert isinstance(result, dict), f"Tool {tool_name} didn't return dict"
    print(f"  ✓ All {len(valid_tools)} tools dispatch correctly")

    print("  PASSED\n")
    return True


# =========================================================================
# PM9.6 — Full chat flow
# =========================================================================

def test_pm96_full_chat_flow():
    """PM9.6: End-to-end chat flow simulation."""
    print("=" * 60)
    print("PM9.6: Full Chat Flow")
    print("=" * 60)

    # Simulate a complete chat interaction
    questions = [
        "¿Cuánto mide el Salón?",
        "¿Qué material tienen los tabiques?",
        "¿Qué escala tiene el plano?",
        "¿Cuántas puertas hay en total?",
        "¿Cuánto cuesta el forjado?",
    ]

    for question in questions:
        # 1. Classify
        topics = classify_question(question)

        # 2. Build queries
        queries = build_search_queries(question)

        # 3. Retrieve context (simulated)
        context = [
            {
                "text": f"Respuesta simulada para: {question}",
                "document_id": 1,
                "document_type": "plano_arquitectura",
                "filename": "test.pdf",
                "confidence": 0.8,
            }
        ]

        # 4. Generate answer
        response = generate_grounded_answer(question, context)

        # 5. Validate
        assert response.answer
        assert response.sources

        print(f"  Q: {question}")
        print(f"    Topics: {topics}")
        print(f"    Sources: {len(response.sources)}")
        print(f"    Answer: {response.answer[:80]}...")
        print()

    print("  PASSED\n")
    return True


if __name__ == "__main__":
    results = []
    results.append(("PM9.1 Tool Definitions", test_pm91_tool_definitions()))
    results.append(("PM9.2 Question Classification", test_pm92_question_classification()))
    results.append(("PM9.3 Search Queries", test_pm93_search_queries()))
    results.append(("PM9.4 Answer Generation", test_pm94_answer_generation()))
    results.append(("PM9.5 Tool Execution", test_pm95_tool_execution()))
    results.append(("PM9.6 Full Chat Flow", test_pm96_full_chat_flow()))

    print("=" * 60)
    print("RESULTS SUMMARY")
    print("=" * 60)
    for name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {status} — {name}")

    all_passed = all(r[1] for r in results)
    print(f"\n{'ALL TESTS PASSED' if all_passed else 'SOME TESTS FAILED'}")
    sys.exit(0 if all_passed else 1)
