"""Unit tests for the Graph RAG review queue service.

The HTTP routes (``admin_graph_review``) are intentionally thin;
the unit tests cover the service so the route handlers stay
declarative. The mock session follows the same pattern used in
``test_graph_extraction``: capture the SQLAlchemy calls and
respond with the fixtures the test prepared, so the assertions
stay independent of any real PostgreSQL instance.
"""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def _review_row(review_id: int = 1, status: str = "pending", confidence: float | None = 0.42):
    return SimpleNamespace(
        id=review_id,
        target_type="relation",
        target_id=42,
        status=status,
        confidence=confidence,
        rationale="low confidence",
        created_at=datetime(2026, 7, 16, tzinfo=UTC),
        submitted_by_job_id=7,
    )


def _relation_row(relation_id: int = 42, status: str = "pending"):
    return SimpleNamespace(id=relation_id, relation_type="shared_reference", status=status)


def _user(user_id: int = 11):
    return SimpleNamespace(id=user_id, email="reviewer@example.com")


class _Session:
    """Capture the calls the service makes and replay them deterministically."""

    def __init__(self, rows: list, relation: _relation_row | None = None) -> None:
        self._rows = list(rows)
        self._relation = relation
        self.added: list[object] = []
        self.flushed = 0
        self.committed = False
        self.get_calls: list[tuple[object, int]] = []
        self.scalar_calls = 0

    def get(self, model, item_id):  # noqa: D401 - stub
        self.get_calls.append((model, item_id))
        # Two flavours of ``get``: the relation lookup and the review
        # row lookup. We dispatch by model class name to keep the
        # test free of import-time model wiring.
        if model.__name__ == "GraphRelation" and self._relation is not None and item_id == self._relation.id:
            return self._relation
        return None

    def execute(self, _stmt):  # noqa: D401 - stub
        self.scalar_calls += 1
        return self

    def scalars(self, _stmt):  # noqa: D401 - stub
        return self

    @property
    def all_rows(self):  # for compatibility with the service's chained API
        return self._rows

    def scalar(self, _stmt):  # noqa: D401 - stub
        return 0

    def flush(self):  # noqa: D401 - stub
        self.flushed += 1

    def commit(self):  # noqa: D401 - stub
        self.committed = True

    def add(self, item):  # noqa: D401 - stub
        self.added.append(item)


# ---------------------------------------------------------------------------
# list_review_queue
# ---------------------------------------------------------------------------


def test_list_review_queue_returns_summary_for_relations(monkeypatch):
    from app.services import graph_review

    relation = _relation_row()
    review = _review_row()

    session = _Session(rows=[(review, relation)])
    # Patch the chained ``.execute(...).all()`` to return the rows.
    execute_result = MagicMock()
    execute_result.all.return_value = [(review, relation)]
    session.execute = MagicMock(return_value=execute_result)  # type: ignore[assignment]
    session.scalar = MagicMock(return_value=0)  # type: ignore[assignment]

    items, total_pending, total_escalated = graph_review.list_review_queue(session, limit=10, offset=0)  # type: ignore[arg-type]
    assert items[0]["summary"] == "relation 42 — shared_reference"
    assert items[0]["target_id"] == 42
    assert total_pending == 0
    assert total_escalated == 0


def test_list_review_queue_summary_falls_back_to_target_type():
    from app.services import graph_review

    review = SimpleNamespace(
        id=2,
        target_type="entity",
        target_id=99,
        status="pending",
        confidence=0.3,
        rationale=None,
        created_at=datetime(2026, 7, 16, tzinfo=UTC),
        submitted_by_job_id=None,
    )

    session = _Session(rows=[(review, None)])
    execute_result = MagicMock()
    execute_result.all.return_value = [(review, None)]
    session.execute = MagicMock(return_value=execute_result)  # type: ignore[assignment]
    # First ``scalar`` call returns the pending count, second the
    # escalated count; the test asserts the pending value.
    session.scalar = MagicMock(side_effect=[1, 0])  # type: ignore[assignment]

    items, total_pending, _ = graph_review.list_review_queue(session)  # type: ignore[arg-type]
    assert items[0]["summary"] == "entity 99"
    assert total_pending == 1


# ---------------------------------------------------------------------------
# decide_review
# ---------------------------------------------------------------------------


def test_decide_review_approved_flips_relation_status():
    from app.services import graph_review

    review = _review_row()
    relation = _relation_row(status="pending")
    session = _Session(rows=[], relation=relation)
    session.get = MagicMock(  # type: ignore[assignment]
        side_effect=lambda model, item_id: relation if model.__name__ == "GraphRelation" and item_id == 42 else review
    )

    result = graph_review.decide_review(
        session,  # type: ignore[arg-type]
        item_id=1,
        user=_user(),  # type: ignore[arg-type]
        decision="approved",
        rationale="looks good",
    )
    assert result["status"] == "approved"
    assert relation.status == "verified"
    # The audit log is mirrored to the session.
    assert any(getattr(item, "action", "") == "graph_review_decision" for item in session.added)


def test_decide_review_rejected_leaves_relation_pending():
    from app.services import graph_review

    review = _review_row()
    relation = _relation_row(status="pending")
    session = _Session(rows=[], relation=relation)
    session.get = MagicMock(  # type: ignore[assignment]
        side_effect=lambda model, item_id: relation if model.__name__ == "GraphRelation" and item_id == 42 else review
    )

    graph_review.decide_review(
        session,  # type: ignore[arg-type]
        item_id=1,
        user=_user(),  # type: ignore[arg-type]
        decision="rejected",
        rationale="duplicate",
    )
    assert relation.status == "pending"


def test_decide_review_404_when_missing():
    from fastapi import HTTPException

    from app.services import graph_review

    session = _Session(rows=[])
    session.get = MagicMock(return_value=None)  # type: ignore[assignment]

    with pytest.raises(HTTPException) as exc:
        graph_review.decide_review(
            session,  # type: ignore[arg-type]
            item_id=999,
            user=_user(),  # type: ignore[arg-type]
            decision="approved",
            rationale=None,
        )
    assert exc.value.status_code == 404


def test_decide_review_409_when_already_decided():
    from fastapi import HTTPException

    from app.services import graph_review

    session = _Session(rows=[])
    session.get = MagicMock(return_value=_review_row(status="approved"))  # type: ignore[assignment]

    with pytest.raises(HTTPException) as exc:
        graph_review.decide_review(
            session,  # type: ignore[arg-type]
            item_id=1,
            user=_user(),  # type: ignore[arg-type]
            decision="rejected",
            rationale=None,
        )
    assert exc.value.status_code == 409
