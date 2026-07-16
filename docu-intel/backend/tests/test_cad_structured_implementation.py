from __future__ import annotations

from pathlib import Path
import json

from app.ai.tools import select_tools_for_question
from app.parsers.dxf import parse_dxf


def test_generic_plan_measurement_question_uses_native_cad_context(monkeypatch):
    monkeypatch.setattr("app.ai.tools.settings.cad_chat_tools_enabled", True)
    tools = select_tools_for_question("¿qué medidas aparecen en el plano?")
    assert tools[0].name == "get_plan_cad_context"


def test_identifier_and_unit_cad_questions_use_native_context(monkeypatch):
    monkeypatch.setattr("app.ai.tools.settings.cad_chat_tools_enabled", True)
    for question in (
        "¿Qué elementos M1-M6 aparecen?",
        "¿Qué cotas tiene M3?",
        "¿En qué unidad está el dibujo?",
        "¿Dónde está M4?",
        "¿Hay alguna cota con unidad dudosa?",
    ):
        tools = select_tools_for_question(question)
        assert tools[0].name == "get_plan_cad_context"


def test_room_measurement_question_keeps_room_tool():
    tools = select_tools_for_question("¿cuánto mide el salón?")
    assert tools[0].name == "search_plan_room_measurements"


def test_cad_filename_with_measurement_words_keeps_native_cad_route(monkeypatch):
    monkeypatch.setattr("app.ai.tools.settings.cad_chat_tools_enabled", True)

    tools = select_tools_for_question(
        "Que datos tiene el plano medidas para mostrador recepcion.dwg?"
    )

    assert [tool.name for tool in tools] == [
        "find_document_by_filename",
        "get_document_full_details",
        "get_plan_cad_context",
    ]


def test_dxf_parser_keeps_circle_and_insert_provenance(tmp_path: Path):
    import ezdxf

    source = tmp_path / "fixture.dxf"
    doc = ezdxf.new("R2013")
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    msp.add_circle((10, 20), radius=3, dxfattribs={"layer": "WALLS"})
    if "DOOR" not in doc.blocks:
        doc.blocks.new("DOOR")
    insert = msp.add_blockref("DOOR", (5, 6), dxfattribs={"layer": "DOORS", "rotation": 15})
    insert.dxf.xscale = 2
    doc.saveas(source)

    extracted = parse_dxf(source, tmp_path)

    assert extracted.cad is not None
    assert extracted.cad.metadata.unit == "mm"
    assert any(entity.entity_type == "circle" for entity in extracted.cad.geometry)
    door = next(entity for entity in extracted.cad.inserts if entity.block_name == "DOOR")
    assert door.rotation == 15
    assert door.scale == (2.0, 1.0, 1.0)


def test_dxf_parser_keeps_legacy_polyline_geometry(tmp_path: Path):
    import ezdxf

    source = tmp_path / "legacy-polyline.dxf"
    doc = ezdxf.new("R2013")
    polyline = doc.modelspace().add_polyline2d([(0, 0), (10, 0), (10, 10)])
    polyline.close()
    doc.saveas(source)

    extracted = parse_dxf(source, tmp_path)

    assert extracted.cad is not None
    geometry = next(entity for entity in extracted.cad.geometry if entity.entity_type == "polyline")
    assert geometry.closed is True
    assert geometry.geometry["points"] == [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]


def test_cad_fixture_manifest_matches_parser():
    fixture_dir = Path(__file__).parent / "fixtures" / "cad"
    expected = json.loads((fixture_dir / "manifest.json").read_text(encoding="utf-8"))["fixture_simple.dxf"]
    extracted = parse_dxf(fixture_dir / "fixture_simple.dxf", fixture_dir)
    assert extracted.cad is not None
    assert len(extracted.cad.texts) == expected["texts"]
    assert len(extracted.cad.dimensions) == expected["dimensions"]
    assert len(extracted.cad.inserts) == expected["inserts"]
    assert {entity.entity_type for entity in extracted.cad.geometry} >= set(expected["geometry_types"])
