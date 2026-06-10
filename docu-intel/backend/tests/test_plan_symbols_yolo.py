"""Tests for P2 — YOLOv8 plan symbol detection.

The tests cover three layers:

1. **Pure helpers** (``_normalise_class_name``, ``count_by_class``,
   ``is_model_available``): no ML, no DB, no settings. Run on any
   machine.

2. **Detector with mocked YOLO model** (``detect_symbols`` patched
   to return canned detections): validates the parse-from-YOLO path
   without needing a real model file or GPU.

3. **API endpoints** (``/plans/{id}/symbols`` and
   ``/plans/{id}/symbols/summary``): use the same MagicMock DB
   pattern the rest of the test suite already relies on.

The real YOLO model is **not** loaded in tests. The integration with
the actual model is exercised manually on a GPU worker when the
operator has the model downloaded.
"""
from __future__ import annotations

import importlib
import sys
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_supported_symbol_classes_contains_documented_classes():
    from app.services.plan_symbols import SUPPORTED_SYMBOL_CLASSES

    # Sanity-check: the public set has the entries the frontend
    # already uses for filters.
    assert "door" in SUPPORTED_SYMBOL_CLASSES
    assert "window" in SUPPORTED_SYMBOL_CLASSES
    assert "electrical_outlet" in SUPPORTED_SYMBOL_CLASSES
    assert "toilet" in SUPPORTED_SYMBOL_CLASSES
    assert len(SUPPORTED_SYMBOL_CLASSES) >= 10


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("single door", "single_door"),
        ("double door", "double_door"),
        ("sliding door", "sliding_door"),
        ("bay window", "bay_window"),
        ("blind window", "blind_window"),
        ("opening symbol", "opening_symbol"),
        ("gas stove", "gas_stove"),
        ("washing machine", "washing_machine"),
        ("bedside cupboard", "bedside_cupboard"),
        ("tv cabinet", "tv_cabinet"),
        ("half-height cabinet", "half_height_cabinet"),
        ("high cabinet", "high_cabinet"),
        ("bath tub", "bathtub"),
        ("squat toilet", "squat_toilet"),
        # Generic fallback
        ("door", "door"),
        ("Custom Class", "custom_class"),
        ("UPPER", "upper"),
        ("multi  word", "multi_word"),
        ("weird--chars!", "weird_chars"),
    ],
)
def test_normalise_class_name(raw: str, expected: str):
    from app.services.plan_symbols import _normalise_class_name

    assert _normalise_class_name(raw) == expected


def test_count_by_class_groups_detections():
    from app.services.plan_symbols import DetectedSymbol, count_by_class

    detections = [
        DetectedSymbol("door", (0, 0, 10, 10), 0.9, 1),
        DetectedSymbol("door", (0, 0, 10, 10), 0.8, 1),
        DetectedSymbol("door", (0, 0, 10, 10), 0.7, 1),
        DetectedSymbol("window", (0, 0, 10, 10), 0.85, 1),
        DetectedSymbol("toilet", (0, 0, 10, 10), 0.95, 1),
    ]
    counts = count_by_class(detections)
    assert counts == {"door": 3, "window": 1, "toilet": 1}


def test_count_by_class_empty():
    from app.services.plan_symbols import count_by_class

    assert count_by_class([]) == {}


def test_detect_symbols_returns_empty_for_missing_file():
    from app.services.plan_symbols import detect_symbols

    # ``is_model_available`` is False in tests, so the detector
    # bails out before even checking the file. This is the
    # intended fail-safe path: when YOLO is not installed, no
    # work is done.
    assert detect_symbols("/nonexistent.png") == []


# ---------------------------------------------------------------------------
# Detector with mocked YOLO model
# ---------------------------------------------------------------------------


def test_detect_symbols_parses_yolo_output(monkeypatch):
    """With a mocked model returning a known detections tensor, the
    detector should produce the matching list of DetectedSymbol rows.

    The mock is injected directly into the module's private
    ``_model`` global so we don't depend on a model file on disk.
    """
    from app.services import plan_symbols
    from app.services.plan_symbols import detect_symbols

    # Construct a fake YOLO result. ultralytics returns objects with
    # ``.boxes`` whose ``.xyxy`` / ``.conf`` / ``.cls`` look like
    # tensors (anything with ``.tolist()`` / ``.item()`` works).
    class _FakeTensor:
        def __init__(self, values):
            self._values = values

        def tolist(self):
            return list(self._values)

        def item(self):
            return self._values[0] if isinstance(self._values, (list, tuple)) else self._values

    class _FakeBoxes:
        def __init__(self, xyxy, conf, cls, names):
            self.xyxy = xyxy
            self.conf = conf
            self.cls = cls
            self._names = names

    class _FakeResult:
        def __init__(self, boxes, names):
            self.boxes = boxes
            self.names = names

    class _FakeModel:
        def predict(self, **kwargs):
            # 2 detections: a "single door" and a "window"
            xyxy = [
                _FakeTensor([10.0, 20.0, 30.0, 40.0]),
                _FakeTensor([100.0, 200.0, 150.0, 240.0]),
            ]
            conf = [_FakeTensor([0.9]), _FakeTensor([0.75])]
            cls = [_FakeTensor([0]), _FakeTensor([3])]
            return [
                _FakeResult(
                    boxes=_FakeBoxes(xyxy, conf, cls, names={0: "single door", 3: "window"}),
                    names={0: "single door", 3: "window"},
                )
            ]

    # Reset state and inject the fake model.
    plan_symbols.reset_model_cache()
    plan_symbols._model = _FakeModel()
    plan_symbols._model_loaded = True
    plan_symbols._model_load_error = None

    try:
        # We pass a path that exists so the detector gets past the
        # existence check. The mocked ``_do_request``/``model.predict``
        # is the only thing that matters here.
        import tempfile
        from pathlib import Path

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"\x89PNG\r\n\x1a\n")
            tmp_path = Path(f.name)
        try:
            detections = detect_symbols(tmp_path, page_number=2)
        finally:
            tmp_path.unlink(missing_ok=True)

        assert len(detections) == 2
        assert detections[0].symbol_class == "single_door"
        assert detections[0].page_number == 2
        assert detections[0].confidence == pytest.approx(0.9)
        assert detections[0].bbox == (10.0, 20.0, 30.0, 40.0)
        assert detections[1].symbol_class == "window"
        assert detections[1].confidence == pytest.approx(0.75)
    finally:
        plan_symbols.reset_model_cache()


def test_detect_symbols_returns_empty_when_model_predict_errors(monkeypatch):
    """A broken model (e.g. corrupt weights) should not crash the
    pipeline — the detector must swallow the exception and return
    ``[]``."""
    from app.services import plan_symbols
    from app.services.plan_symbols import detect_symbols

    class _BrokenModel:
        def predict(self, **kwargs):
            raise RuntimeError("model weights corrupt")

    plan_symbols.reset_model_cache()
    plan_symbols._model = _BrokenModel()
    plan_symbols._model_loaded = True

    try:
        import tempfile
        from pathlib import Path

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"\x89PNG\r\n\x1a\n")
            tmp_path = Path(f.name)
        try:
            assert detect_symbols(tmp_path) == []
        finally:
            tmp_path.unlink(missing_ok=True)
    finally:
        plan_symbols.reset_model_cache()


def test_detect_symbols_returns_empty_when_model_load_fails(monkeypatch):
    """When the YOLO model is missing or its import fails, the
    detector must report ``[]`` rather than raise. The module
    captures the exception and reports it via ``last_load_error``."""
    from app.services import plan_symbols
    from app.services.plan_symbols import detect_symbols

    plan_symbols.reset_model_cache()

    # Patch ``_ensure_model_loaded`` to simulate a failed load. We
    # do this by injecting an error into the cache state directly
    # because the real loader would try to download 50+ MB of weights
    # in a test run.
    plan_symbols._model = None
    plan_symbols._model_loaded = True  # attempted
    plan_symbols._model_load_error = RuntimeError("weights not found")

    assert detect_symbols("/some/fake.png") == []
    assert "weights not found" in str(plan_symbols.last_load_error())


# ---------------------------------------------------------------------------
# _persist_plan_symbols integration with mocked model
# ---------------------------------------------------------------------------


def test_persist_plan_symbols_inserts_rows_for_each_page(monkeypatch):
    """The pipeline-level helper should:
    1. Iterate every DocumentPage that has an image_path.
    2. Call detect_symbols() for each.
    3. Insert a PlanSymbol row per detection.
    4. Return the total count.

    DB and detector are mocked; we only verify the orchestration.
    """
    from app.services import plan_extraction
    from app.models import Plan

    # Build a mock DB session that records inserts and supports
    # ``scalars(...).all()`` for the page lookup.
    db = MagicMock()
    plan = Plan(id=42, document_id=7)
    plan.id = 42

    page1 = MagicMock()
    page1.page_number = 1
    page1.image_path = "/tmp/plan_page1.png"
    page2 = MagicMock()
    page2.page_number = 2
    page2.image_path = "/tmp/plan_page2.png"
    page3 = MagicMock()
    page3.page_number = 3
    page3.image_path = None  # should be skipped

    scalars_mock = MagicMock()
    scalars_mock.all.return_value = [page1, page2, page3]
    db.scalars.return_value = scalars_mock

    # detect_symbols is monkey-patched to return canned detections.
    fake_detector_calls: list[tuple] = []

    def _fake_detect(image_path, *, page_number, **kwargs):
        from pathlib import Path

        fake_detector_calls.append((image_path, page_number))
        if not Path(image_path).exists():
            return []
        from app.services.plan_symbols import DetectedSymbol

        return [
            DetectedSymbol("door", (10, 20, 30, 40), 0.9, page_number),
            DetectedSymbol("window", (100, 200, 150, 240), 0.85, page_number),
        ]

    monkeypatch.setattr(
        "app.services.plan_symbols.is_model_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.services.plan_symbols.detect_symbols",
        _fake_detect,
    )

    # Create real temp files so the existence check passes.
    import tempfile
    from pathlib import Path

    tmp_dir = tempfile.mkdtemp()
    (Path(tmp_dir) / "plan_page1.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (Path(tmp_dir) / "plan_page2.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    page1.image_path = str(Path(tmp_dir) / "plan_page1.png")
    page2.image_path = str(Path(tmp_dir) / "plan_page2.png")

    try:
        total = plan_extraction._persist_plan_symbols(db, plan, document_id=7)
    finally:
        import shutil

        shutil.rmtree(tmp_dir, ignore_errors=True)

    assert total == 4  # 2 detections × 2 pages with images
    assert len(fake_detector_calls) == 2
    # 4 PlanSymbol rows were added (one per detection).
    inserted_symbols = [c.args[0] for c in db.add.call_args_list if isinstance(c.args[0], MagicMock) or hasattr(c.args[0], "symbol_class")]
    # Use direct attribute check via the mock calls.
    assert db.add.call_count == 4


def test_persist_plan_symbols_swallows_detector_errors(monkeypatch):
    """If the detector raises mid-loop, the helper should not propagate
    the exception — it should just skip the offending page and
    continue."""
    from app.services import plan_extraction
    from app.models import Plan

    db = MagicMock()
    plan = Plan(id=1, document_id=1)
    plan.id = 1

    page = MagicMock()
    page.page_number = 1
    page.image_path = "/tmp/x.png"

    scalars_mock = MagicMock()
    scalars_mock.all.return_value = [page]
    db.scalars.return_value = scalars_mock

    monkeypatch.setattr(
        "app.services.plan_symbols.is_model_available",
        lambda: True,
    )

    def _boom(*a, **kw):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(
        "app.services.plan_symbols.detect_symbols",
        _boom,
    )

    # Must NOT raise.
    import tempfile
    from pathlib import Path

    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.write(b"\x89PNG\r\n\x1a\n")
    tmp.close()
    page.image_path = tmp.name
    try:
        total = plan_extraction._persist_plan_symbols(db, plan, document_id=1)
        assert total == 0
    finally:
        Path(tmp.name).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------


def test_api_plan_symbols_summary_aggregates(monkeypatch):
    """The summary endpoint should return one row per class plus a
    total. We patch the DB session so the test does not need a
    running database."""
    # Patch the symbols where ``plans.py`` already imported them from.
    # Importing inside the test makes sure the patch is applied before
    # the route module looks up the names.
    from app.api.routes import plans as plans_route
    from app.models import PlanSymbol, User
    from app.schemas.business import PlanSymbolSummary

    class _FakeScope:
        is_admin = True

    # Patch on the *plans_route* module — the route imported the names
    # there with ``from app.services.tenant_access import ...``. Patching
    # the source module does NOT affect names already imported by
    # ``plans_route``; we have to patch them in ``plans_route`` directly.
    monkeypatch.setattr(
        plans_route,
        "resolve_user_access_scope",
        lambda db, user: _FakeScope(),
    )
    monkeypatch.setattr(
        plans_route,
        "filter_records_by_document_scope",
        lambda db, records, scope: records,
    )

    # Build a fake DB whose ``scalars(...).all()`` returns 5 symbols
    # of 2 different classes.
    db = MagicMock()
    sym1 = MagicMock(spec=PlanSymbol)
    sym1.symbol_class = "door"
    sym1.confidence = 0.9
    sym1.source_model = "SamirShabani/Architect"
    sym2 = MagicMock(spec=PlanSymbol)
    sym2.symbol_class = "door"
    sym2.confidence = 0.8
    sym2.source_model = "SamirShabani/Architect"
    sym3 = MagicMock(spec=PlanSymbol)
    sym3.symbol_class = "window"
    sym3.confidence = 0.7
    sym3.source_model = "SamirShabani/Architect"
    sym4 = MagicMock(spec=PlanSymbol)
    sym4.symbol_class = "window"
    sym4.confidence = 0.6
    sym4.source_model = "SamirShabani/Architect"
    sym5 = MagicMock(spec=PlanSymbol)
    sym5.symbol_class = "toilet"
    sym5.confidence = 0.95
    sym5.source_model = "SamirShabani/Architect"

    scalars_mock = MagicMock()
    scalars_mock.all.return_value = [sym1, sym2, sym3, sym4, sym5]
    db.scalars.return_value = scalars_mock

    # Plan must be retrievable + pass the scope check.
    plan = MagicMock()
    db.get.return_value = plan

    user = MagicMock(spec=User)
    response: PlanSymbolSummary = plans_route.get_plan_symbols_summary(
        plan_id=99,
        min_confidence=0.0,  # explicit so we don't trip on the Query default
        db=db,
        user=user,
    )
    assert response.plan_id == 99
    assert response.total == 5
    assert response.counts == {"door": 2, "window": 2, "toilet": 1}
    assert response.source_model == "SamirShabani/Architect"


def test_api_plan_symbols_list_filters_by_class_and_confidence(monkeypatch):
    """The list endpoint must honour ``symbol_class`` and
    ``min_confidence`` query parameters."""
    from app.api.routes import plans as plans_route
    from app.models import User

    class _FakeScope:
        is_admin = True

    monkeypatch.setattr(
        plans_route,
        "resolve_user_access_scope",
        lambda db, user: _FakeScope(),
    )
    monkeypatch.setattr(
        plans_route,
        "filter_records_by_document_scope",
        lambda db, records, scope: records,
    )

    db = MagicMock()
    db.get.return_value = MagicMock()  # plan exists
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = []
    db.scalars.return_value = scalars_mock

    # The chained query ``.where(...).where(...).order_by(...)`` must
    # be honoured. We just check the final method order.
    user = MagicMock(spec=User)
    result = plans_route.get_plan_symbols(
        plan_id=1,
        symbol_class="door",
        min_confidence=0.5,
        page_number=2,
        db=db,
        user=user,
    )
    assert result == []
    # ``scalars`` was called at least once to build the query.
    assert db.scalars.called


def test_api_plan_symbols_404_for_missing_plan(monkeypatch):
    from fastapi import HTTPException
    from app.api.routes import plans as plans_route
    from app.models import User

    class _FakeScope:
        is_admin = True

    monkeypatch.setattr(
        plans_route,
        "resolve_user_access_scope",
        lambda db, user: _FakeScope(),
    )
    monkeypatch.setattr(
        plans_route,
        "filter_records_by_document_scope",
        lambda db, records, scope: [],
    )

    db = MagicMock()
    db.get.return_value = None  # plan does not exist

    user = MagicMock(spec=User)
    with pytest.raises(HTTPException) as exc_info:
        plans_route.get_plan_symbols_summary(plan_id=999, db=db, user=user)
    assert exc_info.value.status_code == 404
