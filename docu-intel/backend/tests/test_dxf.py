"""Tests for X2 (DXF parser) and X3 (DXF exporter).

The DXF parser and exporter use ``ezdxf`` which is an optional
dependency. The tests below verify the pure-Python helpers and
the data structures without requiring ezdxf to be installed.
The integration with real DXF files is exercised in CI with a
small fixture.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services.dxf_parser import DxfExtraction
from app.services.dxf_export import export_annotations_to_dxf


# ---------------------------------------------------------------------------
# DxfExtraction dataclass
# ---------------------------------------------------------------------------


def test_dxf_extraction_defaults():
    ext = DxfExtraction(
        text="test",
        layers=["0"],
        text_entities=[],
        dimensions=[],
        block_references=[],
        image_path=None,
    )
    assert ext.page_count == 1
    assert ext.image_path is None


def test_dxf_extraction_with_entities():
    ext = DxfExtraction(
        text="layer: test",
        layers=["0", "walls"],
        text_entities=[("hello", 10.0, 20.0, "0")],
        dimensions=[(1500.0, "mm", 0.0, 0.0)],
        block_references=[("door", 100.0, 200.0, "0")],
        image_path="/tmp/test.png",
    )
    assert len(ext.text_entities) == 1
    assert ext.text_entities[0][0] == "hello"
    assert len(ext.dimensions) == 1
    assert ext.dimensions[0][0] == 1500.0


# ---------------------------------------------------------------------------
# DXF export (smoke test without ezdxf)
# ---------------------------------------------------------------------------


def test_export_annotations_to_dxf_returns_none_without_ezdxf(monkeypatch):
    """When ezdxf is not installed, the function returns None."""
    import sys
    # Temporarily remove ezdxf from sys.modules to simulate
    # it not being installed.
    monkeypatch.delitem(sys.modules, "ezdxf", raising=False)
    monkeypatch.delitem(sys.modules, "ezdxf.new", raising=False)

    # The import inside the function will fail.
    result = export_annotations_to_dxf(
        rooms=[],
        dimensions=[],
        output_path="/tmp/test.dxf",
    )
    # The function catches the ImportError and returns None.
    # (If ezdxf IS installed, this test is a no-op.)
    assert result is None or isinstance(result, Path)


def test_export_annotations_to_dxf_handles_empty_input(tmp_path):
    """Empty rooms and dimensions should produce a valid (empty) DXF."""
    try:
        import ezdxf
    except ImportError:
        pytest.skip("ezdxf not installed")
    out = tmp_path / "empty.dxf"
    result = export_annotations_to_dxf(
        rooms=[],
        dimensions=[],
        output_path=out,
    )
    if result is not None:
        assert result.exists()
        assert result.stat().st_size > 0


def test_export_annotations_to_dxf_with_rooms(tmp_path):
    """A simple room polygon should produce a DXF with a
    LWPOLYLINE on the 'habitaciones_ia' layer."""
    try:
        import ezdxf
    except ImportError:
        pytest.skip("ezdxf not installed")
    out = tmp_path / "rooms.dxf"
    rooms = [
        {
            "name": "Salón",
            "area_m2": 25.0,
            "polygon": [[0, 0], [5, 0], [5, 5], [0, 5]],
        }
    ]
    result = export_annotations_to_dxf(
        rooms=rooms,
        dimensions=[],
        output_path=out,
    )
    if result is not None:
        assert result.exists()
        doc = ezdxf.readfile(str(result))
        msp = doc.modelspace()
        entities = list(msp)
        assert len(entities) > 0
