# OCR Live & Flow Timeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a `/admin/ocr-flow` page with two tabs ("Flujo OCR" live + "Flujo Documento" histórico) and a Server-Sent Events stream so the operator can see in real time where each in-flight document is in the pipeline, and can drill into any document to see its full history (parser → cascade OCR → chunks → embeddings → classification → extraction).

**Architecture:**
- **Backend (FastAPI):** a thin `events_bus` module publishes to a Redis pub/sub channel whenever a Celery task transitions (`started`/`finished`/`failed`); an SSE endpoint `GET /admin/ocr-flow/stream` subscribes and forwards events to the browser. Two new REST endpoints expose snapshots: `GET /admin/ocr-flow/live` (active jobs snapshot) and `GET /documents/{id}/flow` (historical timeline assembled from `IngestionEvent`, `ExtractionJob` and `DocumentPage.ocr_engine`).
- **Frontend (React + TanStack Query):** a new `OcrFlowPage` with two `<Tabs>`. The "live" tab uses an `EventSource` hook that reconciles streamed events into a query cache (TanStack Query `setQueryData`); the "document" tab is a per-doc timeline with a deep-link from any row in the live table.
- **One new DB table** (`ocr_cascade_attempts`) added in Task 3 — records every tier tried per page, with success/duration/reason. Migration `0032_ocr_cascade_attempts.py` is part of the same plan. Everything else (`IngestionEvent`, `ExtractionJob`, `DocumentPage`) is consumed read-only.
- **Permissions:** route lives under `/admin/*` → gated by existing `gestor|admin` role check (same as `/admin/quality/ocr-review`).

**Tech Stack:** FastAPI `sse-starlette` (already in the dependency surface for `StreamingResponse` in admin_system), Redis pub/sub (`redis.asyncio` from existing `cache` package), Celery `before_task_publish`/`task_postrun` signals, React `EventSource` + TanStack Query, shadcn/ui `Tabs`+`Table`+`Badge` (all already present).

---

## File Structure

**New files**
- `docu-intel/backend/app/services/events_bus.py` — Redis pub/sub publisher/subscriber used by workers (publish) and the SSE endpoint (subscribe).
- `docu-intel/backend/app/api/routes/ocr_flow.py` — three new endpoints: `/admin/ocr-flow/stream` (SSE), `/admin/ocr-flow/live` (REST snapshot), `/documents/{id}/flow` (historical timeline).
- `docu-intel/backend/app/services/ocr_flow_timeline.py` — pure assembler that takes a `document_id` and returns a list of timeline events (used by the historical endpoint; easy to unit-test).
- `docu-intel/backend/app/models/ocr_cascade.py` — `OcrCascadeAttempt` ORM model (one row per tier tried per page).
- `docu-intel/backend/alembic/versions/0032_ocr_cascade_attempts.py` — Alembic migration for the new table.
- `docu-intel/backend/tests/test_events_bus.py` — unit tests for publish/subscribe with `fakeredis`.
- `docu-intel/backend/tests/test_ocr_flow_timeline.py` — unit tests for the timeline assembler (golden fixture).
- `docu-intel/backend/tests/test_ocr_flow_endpoints.py` — integration test for the three endpoints (auth, snapshot shape, SSE basic).
- `docu-intel/backend/tests/test_cascading_attempt_logging.py` — unit tests for the cascade's per-attempt recorder.
- `docu-intel/frontend/src/api/ocrFlow.ts` — typed client for `live()` and `documentFlow()`.
- `docu-intel/frontend/src/hooks/useOcrFlowStream.ts` — `EventSource` hook that subscribes and pushes events into a TanStack Query cache.
- `docu-intel/frontend/src/pages/admin/AdminOcrFlowRoute.tsx` — route entry that mounts the page (lazy-loaded per F4).
- `docu-intel/frontend/src/pages/admin/AdminOcrFlowTab.tsx` — the actual UI (two tabs + tables + timeline).
- `docu-intel/frontend/src/pages/admin/useAdminOcrFlowData.ts` — TanStack Query hooks for the snapshot + historical endpoints.
- `docu-intel/frontend/src/pages/admin/useAdminOcrFlowData.test.ts` — minimal test on the query keys.
- `docu-intel/frontend/src/pages/admin/AdminOcrFlowTab.test.tsx` — smoke test (renders both tabs, switches between them).

**Modified files**
- `docu-intel/backend/app/models/__init__.py` — re-export `OcrCascadeAttempt`.
- `docu-intel/backend/app/workers/celery_app.py` — wire `before_task_publish` / `task_postrun` / `task_failure` to publish via `events_bus.publish`.
- `docu-intel/backend/app/ocr/cascading.py` — accept an optional per-call context (`document_id`, `page_id`) injected via setattr by the parser; persist every tier attempt to `OcrCascadeAttempt` via a small callback. **The `BaseOCREngine` Protocol and the public `extract(image_path)` signature are not changed.**
- `docu-intel/backend/app/parsers/pdf.py` — set the cascade's `current_document_id` / `current_page_id` before each `extract` call (same pattern already used for `current_language`).
- `docu-intel/backend/app/parsers/image.py` — same setattr hook.
- `docu-intel/backend/app/api/routes/__init__.py` — register the new router.
- `docu-intel/backend/app/api/routes/admin_ocr_stats.py` — *no logic change*; just reference point for patterns (read only).
- `docu-intel/frontend/src/routes/router.tsx` — add the lazy route `/admin/flujo-ocr` under the `admin` layout.
- `docu-intel/frontend/src/routes/adminTabs.ts` — add the new tab entry.
- `docu-intel/frontend/src/components/layout/Sidebar.tsx` — add the navigation link to the new admin page (matching the pattern for the other admin tabs).
- `docu-intel/frontend/src/types/api.ts` — add `OcrFlowLiveJob`, `OcrFlowDocumentStep`, `OcrCascadeAttempt` types.
- `docu-intel/backend/requirements.txt` — verify `sse-starlette` is present (it is, per `admin_system.py` import patterns). If not, add it.
- `docu-intel/docu-intel/frontend/package.json` — *no change*; `EventSource` is browser-native.

---

## Task 1: Events bus (Redis pub/sub)

**Files:**
- Create: `docu-intel/backend/app/services/events_bus.py`
- Test: `docu-intel/backend/tests/test_events_bus.py`

- [ ] **Step 1.1: Write the failing test**

```python
# docu-intel/backend/tests/test_events_bus.py
import asyncio
import json

import pytest

from app.services.events_bus import publish_event, subscribe_events


pytestmark = pytest.mark.asyncio


async def test_publish_then_subscribe_receives_event(monkeypatch):
    """The bus round-trips a JSON event through Redis pub/sub."""
    from app.services import events_bus

    # Use an in-process fake Redis to avoid hitting a real broker.
    class FakeRedis:
        def __init__(self):
            self.published: list[tuple[str, str]] = []
            self._subscribers: list[asyncio.Queue] = []

        async def publish(self, channel: str, message: str) -> int:
            self.published.append((channel, message))
            for q in self._subscribers:
                await q.put((channel, message))
            return len(self._subscribers)

        def pubsub(self):
            outer = self

            class _PubSub:
                async def subscribe(self, channel: str) -> None:
                    outer._subscribers.append(outer._queue)
                    outer._queue = asyncio.Queue()

                async def listen(self):
                    while True:
                        ch, msg = await outer._queue.get()
                        yield {"type": "message", "channel": ch, "data": msg}

                async def unsubscribe(self) -> None:
                    outer._subscribers.clear()

                async def close(self) -> None:
                    pass

            return _PubSub()

        _queue: asyncio.Queue = asyncio.Queue()

    fake = FakeRedis()
    monkeypatch.setattr(events_bus, "get_redis", lambda: fake)

    await publish_event("ocr_flow", {"job_id": 1, "status": "started"})
    received: list[dict] = []

    async def consumer() -> None:
        async for msg in subscribe_events("ocr_flow"):
            received.append(msg)
            if len(received) >= 1:
                return

    await asyncio.wait_for(consumer(), timeout=1.0)
    assert received == [{"job_id": 1, "status": "started"}]
    assert fake.published[0][0] == "ocr_flow"
```

- [ ] **Step 1.2: Run the test to verify it fails**

Run: `cd docu-intel/backend && python -m pytest tests/test_events_bus.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.events_bus'`.

- [ ] **Step 1.3: Implement the bus**

```python
# docu-intel/backend/app/services/events_bus.py
"""Thin Redis pub/sub wrapper used by Celery workers and the SSE endpoint.

The bus is intentionally tiny: the publisher and the subscriber do not share
state (they talk through Redis), so any number of workers and any number of
SSE clients can run side by side. We never store events — a subscriber that
comes online after a publish has happened gets no replay.
"""
from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

from app.services.cache import get_redis  # type: ignore[attr-defined]

logger = logging.getLogger("app.services.events_bus")

CHANNEL = "ocr_flow"


async def publish_event(event_type: str, payload: dict[str, Any]) -> None:
    """Publish ``payload`` on the OCR flow channel as JSON."""
    envelope = {"type": event_type, **payload}
    redis = get_redis()
    try:
        await redis.publish(CHANNEL, json.dumps(envelope, default=str))
    except Exception:  # pragma: no cover - never let a publish kill a task
        logger.exception("events_bus.publish failed for %s", event_type)


async def subscribe_events(channel: str = CHANNEL) -> AsyncIterator[dict[str, Any]]:
    """Yield decoded events from ``channel`` until the consumer is cancelled."""
    redis = get_redis()
    pubsub = redis.pubsub()
    await pubsub.subscribe(channel)
    try:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            data = message.get("data")
            if isinstance(data, bytes):
                data = data.decode("utf-8")
            try:
                yield json.loads(data)
            except json.JSONDecodeError:
                logger.warning("events_bus: dropping malformed message: %r", data)
    finally:
        await pubsub.unsubscribe()
        await pubsub.close()


__all__ = ["publish_event", "subscribe_events", "CHANNEL"]
```

> **Note on `app.services.cache`:** the existing Redis factory is imported in
> `app/services/cache/__init__.py`. If the function is named `get_redis_client`
> in this repo, adjust the import accordingly. The test in Step 1.1 patches
> the symbol under whatever name the module exposes (`events_bus.get_redis`).

- [ ] **Step 1.4: Run the test to verify it passes**

Run: `cd docu-intel/backend && python -m pytest tests/test_events_bus.py -v`
Expected: PASS.

- [ ] **Step 1.5: Commit**

```bash
git add docu-intel/backend/app/services/events_bus.py docu-intel/backend/tests/test_events_bus.py
git commit -m "feat(events): add Redis pub/sub bus for OCR flow events"
```

---

## Task 2: Celery signal hook → publish events

**Files:**
- Modify: `docu-intel/backend/app/workers/celery_app.py` (add signal handlers; do not change existing task routing).
- (No new test here; covered by Task 6 integration test.)

- [ ] **Step 2.1: Read the current Celery app**

Run: `cat docu-intel/backend/app/workers/celery_app.py | head -120`
Confirm the file exposes a `celery_app = Celery(...)` instance and a `include=[...]` list.

- [ ] **Step 2.2: Add signal handlers**

Append to `docu-intel/backend/app/workers/celery_app.py` (after the existing `celery_app.conf.update(...)` block):

```python
from celery.signals import (
    before_task_publish,
    task_postrun,
    task_failure,
)

from app.services.events_bus import publish_event


@before_task_publish.connect
def _ocr_flow_on_publish(sender=None, headers=None, body=None, **kwargs) -> None:
    """Announce 'a task is about to start' so the live UI can show a pending row."""
    if not headers:
        return
    task_name = headers.get("task") or sender or "unknown"
    if not task_name.startswith(("app.workers", "app.ocr")):
        return  # don't pollute the channel with maintenance/learning jobs
    # Best-effort: extract document_id from the body without parsing args.
    document_id = None
    if isinstance(body, (list, tuple)) and body:
        first = body[0]
        if isinstance(first, dict):
            document_id = first.get("document_id")
    import asyncio

    async def _go() -> None:
        try:
            await publish_event(
                "job.queued",
                {"task": task_name, "document_id": document_id},
            )
        except Exception:
            pass

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(_go())
        else:
            loop.run_until_complete(_go())
    except RuntimeError:
        # No event loop in this worker thread (Celery prefork); fall back to
        # a blocking call against a fresh loop. The publish is best-effort.
        asyncio.run(_go())


@task_postrun.connect
def _ocr_flow_on_postrun(task_id=None, task=None, args=None, **kwargs) -> None:
    if not task or not task.name.startswith(("app.workers", "app.ocr")):
        return
    document_id = None
    if args and isinstance(args, (list, tuple)) and isinstance(args[0], dict):
        document_id = args[0].get("document_id")
    state = kwargs.get("state") or "finished"
    runtime = kwargs.get("runtime")
    import asyncio

    async def _go() -> None:
        try:
            await publish_event(
                "job.finished" if state == "SUCCESS" else "job.started",
                {
                    "task": task.name,
                    "task_id": task_id,
                    "document_id": document_id,
                    "state": state,
                    "runtime_s": runtime,
                },
            )
        except Exception:
            pass

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(_go())
        else:
            loop.run_until_complete(_go())
    except RuntimeError:
        asyncio.run(_go())


@task_failure.connect
def _ocr_flow_on_failure(task_id=None, task=None, args=None, exception=None, **kwargs) -> None:
    if not task or not task.name.startswith(("app.workers", "app.ocr")):
        return
    document_id = None
    if args and isinstance(args, (list, tuple)) and isinstance(args[0], dict):
        document_id = args[0].get("document_id")
    import asyncio

    async def _go() -> None:
        try:
            await publish_event(
                "job.failed",
                {
                    "task": task.name,
                    "task_id": task_id,
                    "document_id": document_id,
                    "error": str(exception) if exception else None,
                },
            )
        except Exception:
            pass

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(_go())
        else:
            loop.run_until_complete(_go())
    except RuntimeError:
        asyncio.run(_go())
```

- [ ] **Step 2.3: Smoke import**

Run: `cd docu-intel/backend && python -c "from app.workers.celery_app import celery_app; print(celery_app)"
Expected: prints the Celery app's repr without exception.

- [ ] **Step 2.4: Commit**

```bash
git add docu-intel/backend/app/workers/celery_app.py
git commit -m "feat(workers): publish lifecycle events to OCR flow bus"
```

---

## Task 3: `OcrCascadeAttempt` model + Alembic migration

**Files:**
- Create: `docu-intel/backend/app/models/ocr_cascade.py`
- Modify: `docu-intel/backend/app/models/__init__.py`
- Create: `docu-intel/backend/alembic/versions/0032_ocr_cascade_attempts.py`
- Test: `docu-intel/backend/tests/test_ocr_cascade_model.py` (smoke test that the model round-trips).

- [ ] **Step 3.1: Write the failing model test**

```python
# docu-intel/backend/tests/test_ocr_cascade_model.py
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.base import Base
from app.models.document import Document, DocumentPage
from app.models.ocr_cascade import OcrCascadeAttempt


def test_ocr_cascade_attempt_round_trips():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    s.add(Document(id=1, original_filename="a.pdf", file_hash="h"))
    s.add(DocumentPage(id=10, document_id=1, page_number=1))
    s.add(
        OcrCascadeAttempt(
            id=100,
            document_id=1,
            page_id=10,
            page_number=1,
            tier="paddleocr",
            tier_index=2,
            success=True,
            duration_ms=412,
            reason="ok",
            confidence=0.83,
            chars=421,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
    )
    s.commit()
    row = s.get(OcrCascadeAttempt, 100)
    assert row is not None
    assert row.tier == "paddleocr"
    assert row.tier_index == 2
    assert row.success is True
    assert row.duration_ms == 412
    assert row.confidence == 0.83
    assert row.chars == 421
```

- [ ] **Step 3.2: Run the test to verify it fails**

Run: `cd docu-intel/backend && python -m pytest tests/test_ocr_cascade_model.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3.3: Implement the model**

```python
# docu-intel/backend/app/models/ocr_cascade.py
"""Per-tier attempt log for the cascading OCR engine.

The :class:`~app.ocr.cascading.CascadingOCREngine` tries up to four tiers
per page (Tesseract → PaddleOCR → PP-Structure → VLM). This table records
**every** attempt with its outcome so the admin UI can reconstruct the
full cascade trace (e.g. "page 3: Tesseract tried and failed on quality,
PaddleOCR succeeded with 0.83 confidence after 412 ms").

One row per tier tried, per page. The winning tier is not special — it
just has ``success=True``; ``DocumentPage.ocr_engine`` continues to be
the single source of truth for "which engine's text is stored".
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class OcrCascadeAttempt(Base):
    __tablename__ = "ocr_cascade_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    page_id: Mapped[int] = mapped_column(
        ForeignKey("document_pages.id", ondelete="CASCADE"), index=True, nullable=False
    )
    page_number: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    # Engine name (``tesseract``, ``paddleocr``, ``pp_structure``, ``vlm_ocr``).
    tier: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    # Order in the cascade: 1=primary, 2=fallback, 3=pp_structure, 4=vlm.
    tier_index: Mapped[int] = mapped_column(Integer, nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Engine-reported confidence (NULL when the engine raised or the
    # attempt did not produce a usable result).
    confidence: Mapped[float | None] = mapped_column(Float)
    # Length of the engine's text output (used by the cascade to decide
    # whether to escalate; we persist it for forensics).
    chars: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Short reason label: ``"ok"``, ``"no_improvement"``, ``"exception"``,
    # ``"below_quality_threshold"``, ``"language_mismatch"`` … same labels
    # already used in :func:`app.ocr.cascading._should_replace_with_fallback`.
    reason: Mapped[str | None] = mapped_column(String(80))
    # Exception text when ``success=False`` and there was a real exception.
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )


__all__ = ["OcrCascadeAttempt"]
```

- [ ] **Step 3.4: Re-export the model**

In `docu-intel/backend/app/models/__init__.py`, add the import next to the
existing `document` imports and extend `__all__`:

```python
from app.models.ocr_cascade import OcrCascadeAttempt
```

(Plus the corresponding `"OcrCascadeAttempt"` string in `__all__`.)

- [ ] **Step 3.5: Run the test to verify it passes**

Run: `cd docu-intel/backend && python -m pytest tests/test_ocr_cascade_model.py -v`
Expected: PASS.

- [ ] **Step 3.6: Create the Alembic migration**

```python
# docu-intel/backend/alembic/versions/0032_ocr_cascade_attempts.py
"""ocr cascade attempts log

Revision ID: 0032_ocr_cascade_attempts
Revises: 0031_pg_trgm_text_search_indexes
Create Date: 2026-06-12
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0032_ocr_cascade_attempts"
down_revision = "0031_pg_trgm_text_search_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ocr_cascade_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("page_id", sa.Integer(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("tier", sa.String(length=40), nullable=False),
        sa.Column("tier_index", sa.Integer(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("chars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reason", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["page_id"], ["document_pages.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_ocr_cascade_attempts_document_id",
        "ocr_cascade_attempts",
        ["document_id"],
    )
    op.create_index(
        "ix_ocr_cascade_attempts_page_id",
        "ocr_cascade_attempts",
        ["page_id"],
    )
    op.create_index(
        "ix_ocr_cascade_attempts_page_number",
        "ocr_cascade_attempts",
        ["page_number"],
    )
    op.create_index(
        "ix_ocr_cascade_attempts_tier",
        "ocr_cascade_attempts",
        ["tier"],
    )
    op.create_index(
        "ix_ocr_cascade_attempts_success",
        "ocr_cascade_attempts",
        ["success"],
    )
    op.create_index(
        "ix_ocr_cascade_attempts_created_at",
        "ocr_cascade_attempts",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_ocr_cascade_attempts_created_at", table_name="ocr_cascade_attempts")
    op.drop_index("ix_ocr_cascade_attempts_success", table_name="ocr_cascade_attempts")
    op.drop_index("ix_ocr_cascade_attempts_tier", table_name="ocr_cascade_attempts")
    op.drop_index("ix_ocr_cascade_attempts_page_number", table_name="ocr_cascade_attempts")
    op.drop_index("ix_ocr_cascade_attempts_page_id", table_name="ocr_cascade_attempts")
    op.drop_index("ix_ocr_cascade_attempts_document_id", table_name="ocr_cascade_attempts")
    op.drop_table("ocr_cascade_attempts")
```

- [ ] **Step 3.7: Apply the migration locally**

Run: `cd docu-intel/backend && alembic upgrade head`
Expected: prints `Running upgrade 0031_pg_trgm_text_search_indexes -> 0032_ocr_cascade_attempts, ocr cascade attempts log`.

- [ ] **Step 3.8: Commit**

```bash
git add docu-intel/backend/app/models/ocr_cascade.py \
        docu-intel/backend/app/models/__init__.py \
        docu-intel/backend/alembic/versions/0032_ocr_cascade_attempts.py \
        docu-intel/backend/tests/test_ocr_cascade_model.py
git commit -m "feat(ocr-cascade): add OcrCascadeAttempt model + migration"
```

---

## Task 4: Instrument `CascadingOCREngine` to log every attempt

**Files:**
- Modify: `docu-intel/backend/app/ocr/cascading.py`
- Modify: `docu-intel/backend/app/parsers/pdf.py`
- Modify: `docu-intel/backend/app/parsers/image.py`
- Test: `docu-intel/backend/tests/test_cascading_attempt_logging.py`

- [ ] **Step 4.1: Write the failing test**

```python
# docu-intel/backend/tests/test_cascading_attempt_logging.py
import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.base import Base
from app.models.document import Document, DocumentPage
from app.models.ocr_cascade import OcrCascadeAttempt
from app.ocr.base import OCRResult
from app.ocr.cascading import CascadingOCREngine


class _FakeEngine:
    def __init__(self, name: str, text: str = "x" * 60, confidence: float = 0.9):
        self.name = name
        self._text = text
        self._confidence = confidence

    def extract(self, image_path: Path) -> OCRResult:
        return OCRResult(text=self._text, confidence=self._confidence, blocks=[], engine=self.name)


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session(), engine


def test_cascade_records_every_tier_attempt(tmp_path):
    s, _ = _session()
    s.add(Document(id=1, original_filename="a.pdf", file_hash="h"))
    s.add(DocumentPage(id=10, document_id=1, page_number=1))
    s.commit()

    primary = _FakeEngine("tesseract", text="x" * 5, confidence=0.4)  # weak
    fallback = _FakeEngine("paddleocr", text="x" * 80, confidence=0.9)
    cascade = CascadingOCREngine(primary=primary, fallback=fallback)
    cascade.current_document_id = 1
    cascade.current_page_id = 10
    cascade.current_page_number = 1
    cascade.attempt_recorder = lambda row: s.add(OcrCascadeAttempt(**row)) or s.commit()

    fake_image = tmp_path / "page.png"
    fake_image.write_bytes(b"\x89PNG\r\n\x1a\n")
    cascade.extract(fake_image)

    rows = s.query(OcrCascadeAttempt).order_by(OcrCascadeAttempt.tier_index).all()
    assert [r.tier for r in rows] == ["tesseract", "paddleocr"]
    assert rows[0].success is False
    assert rows[0].tier_index == 1
    assert rows[1].success is True
    assert rows[1].tier_index == 2
    assert rows[0].document_id == 1
    assert rows[0].page_id == 10
    assert rows[0].page_number == 1
```

- [ ] **Step 4.2: Run the test to verify it fails**

Run: `cd docu-intel/backend && python -m pytest tests/test_cascading_attempt_logging.py -v`
Expected: FAIL with `AttributeError: 'CascadingOCREngine' object has no attribute 'attempt_recorder'`.

- [ ] **Step 4.3: Add the recorder hook + record every tier in the cascade**

In `docu-intel/backend/app/ocr/cascading.py`, add **two new attributes**
to `CascadingOCREngine.__init__` (default to `None`) and add **two new
attributes** at class level for the per-page context, then call the
recorder from every tier. Apply the edits below.

**(4.3.1) Update `__init__`:**

Replace the existing `__init__` signature + body opening with:

```python
    def __init__(
        self,
        primary: BaseOCREngine,
        fallback: BaseOCREngine,
        *,
        min_chars: int = 30,
        min_confidence: float = 0.5,
        pp_structure: BaseOCREngine | None = None,
        vlm_ocr: BaseOCREngine | None = None,
        tier4_quality_threshold: float = 0.62,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.pp_structure = pp_structure
        self.vlm_ocr = vlm_ocr
        self.min_chars = min_chars
        self.min_confidence = min_confidence
        self.tier4_quality_threshold = tier4_quality_threshold
        # O2 — per-page language context. The parser sets this before
        # each ``extract`` call; the cascade reads it to look up the
        # per-language thresholds. ``None`` means "no detection, use
        # the legacy document-wide constants". The cascade is *not*
        # thread-safe w.r.t. this attribute; the workers that build
        # a fresh cascade per process rely on the parser always
        # setting it before calling.
        self.current_language: str | None = None
        # NEW — per-page document/page context. The parser sets these
        # via setattr (because BaseOCREngine is a Protocol); when the
        # cascade has them, it logs every tier attempt to
        # ``OcrCascadeAttempt`` so the admin can reconstruct the full
        # cascade trace per page.
        self.current_document_id: int | None = None
        self.current_page_id: int | None = None
        self.current_page_number: int | None = None
        # NEW — optional callback the parser injects. Signature:
        # ``recorder(dict) -> None``. Receives a dict matching the
        # ``OcrCascadeAttempt`` columns. We do not import the model
        # here so this module stays free of SQLAlchemy in unit tests
        # that don't need persistence.
        self.attempt_recorder: callable | None = None
        # ``name`` is the engine identity of the last result; default to
        # the primary so a query before any call still has a sensible
        # value.
        self._name: str = primary.name
```

**(4.3.2) Add a private helper that records a tier attempt:**

Append **just below** the existing `_quality` function (or anywhere
top-level in the module, but keep it next to `_quality` for
discoverability):

```python
def _record_attempt(
    cascade: "CascadingOCREngine",
    *,
    tier: str,
    tier_index: int,
    success: bool,
    duration_ms: int,
    confidence: float | None,
    text: str | None,
    reason: str | None = None,
    error_message: str | None = None,
) -> None:
    """Best-effort write of one ``OcrCascadeAttempt`` row.

    No-ops when the parser did not set the per-page context or did
    not inject a recorder. Never raises into the caller.
    """
    if cascade.attempt_recorder is None:
        return
    if cascade.current_document_id is None or cascade.current_page_id is None:
        return
    try:
        cascade.attempt_recorder(
            {
                "document_id": cascade.current_document_id,
                "page_id": cascade.current_page_id,
                "page_number": cascade.current_page_number,
                "tier": tier,
                "tier_index": tier_index,
                "success": success,
                "duration_ms": duration_ms,
                "confidence": confidence,
                "chars": len((text or "").strip()),
                "reason": reason,
                "error_message": error_message,
            }
        )
    except Exception:  # pragma: no cover - recorder must never break OCR
        logger.exception("OCR cascade attempt recorder raised")
```

**(4.3.3) Call the recorder in `extract()` and `_try_tier3` / `_try_tier4`:**

In `extract()`, wrap the primary call so we always log it:

```python
    def extract(self, image_path: Path) -> OCRResult:
        start = time.perf_counter()
        try:
            primary_result = self.primary.extract(image_path)
        except Exception as exc:
            duration_ms = int((time.perf_counter() - start) * 1000)
            track_ocr_duration(time.perf_counter() - start)
            _record_attempt(
                self,
                tier=self.primary.name,
                tier_index=1,
                success=False,
                duration_ms=duration_ms,
                confidence=None,
                text=None,
                reason="exception",
                error_message=str(exc),
            )
            self._track_fallback_failure(self.primary.name, exc)
            raise
        primary_duration_ms = int((time.perf_counter() - start) * 1000)
        track_ocr_duration(time.perf_counter() - start)
        _record_attempt(
            self,
            tier=self.primary.name,
            tier_index=1,
            success=True,
            duration_ms=primary_duration_ms,
            confidence=primary_result.confidence,
            text=primary_result.text,
            reason="ok",
        )

        if self._is_acceptable(primary_result):
            return self._finalize(image_path, self.primary.name, primary_result)

        # Escalate to the fallback. Any failure here is best-effort:
        # we keep the primary result so the user at least sees *some*
        # text instead of a blank page. The vision LLM fallback further
        # downstream catches the truly impossible cases.
        start = time.perf_counter()
        try:
            fallback_result = self.fallback.extract(image_path)
        except Exception as exc:
            duration_ms = int((time.perf_counter() - start) * 1000)
            track_ocr_duration(time.perf_counter() - start)
            self._track_fallback_failure(self.fallback.name, exc)
            _record_attempt(
                self,
                tier=self.fallback.name,
                tier_index=2,
                success=False,
                duration_ms=duration_ms,
                confidence=None,
                text=None,
                reason="exception",
                error_message=str(exc),
            )
            return self._finalize(image_path, self.primary.name, primary_result)
        fallback_duration_ms = int((time.perf_counter() - start) * 1000)
        track_ocr_duration(time.perf_counter() - start)
        _record_attempt(
            self,
            tier=self.fallback.name,
            tier_index=2,
            success=True,
            duration_ms=fallback_duration_ms,
            confidence=fallback_result.confidence,
            text=fallback_result.text,
            reason="ok",
        )

        should_replace, reason = _should_replace_with_fallback(primary_result, fallback_result)
        # ... rest of the function unchanged ...
```

In `_try_tier3`, after the `tier3_result = self.pp_structure.extract(...)`
call (both success and exception paths), add the corresponding
`_record_attempt(self, tier=self.pp_structure.name, tier_index=3, ...)`
call. Mirror the same pattern for `_try_tier4` with `tier_index=4`.

> **Important:** the existing `_record_winner` call already records
> the tier that won. We do **not** touch it; the new recorder only
> fires for *non-winning* tiers (and the primary in any case). For
> the winning tier we already get the row from the per-tier logging
> above; we do not need a second "winner" row.

- [ ] **Step 4.4: Inject the recorder from the parsers**

In `docu-intel/backend/app/parsers/pdf.py`, locate the spot right before
each `ocr_engine.extract(...)` call (search for `ocr_engine = get_ocr_engine_class()()`
or whatever the existing pattern is). Right before the call, add:

```python
try:
    setattr(
        ocr_engine,
        "current_document_id",
        getattr(self, "document_id", None) or document_id,
    )
    setattr(ocr_engine, "current_page_id", getattr(page, "id", None))
    setattr(ocr_engine, "current_page_number", index)  # 1-based page number
    recorder = _build_cascade_recorder(db)
    if recorder is not None:
        setattr(ocr_engine, "attempt_recorder", recorder)
except Exception:  # pragma: no cover - defensive
    pass
```

And add the helper at module top (after the imports, before the first
class/function):

```python
def _build_cascade_recorder(db: Session) -> "callable | None":
    """Return a closure that persists one ``OcrCascadeAttempt`` per tier.

    Returns ``None`` when ``db`` is not a real session (e.g. in unit
    tests that exercise the cascade without a DB).
    """
    if db is None:
        return None

    from app.models.ocr_cascade import OcrCascadeAttempt

    def _record(row: dict) -> None:
        try:
            db.add(OcrCascadeAttempt(**row))
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Failed to persist OcrCascadeAttempt row")

    return _record
```

> The `Session` type is already imported in this file. If not, add
> `from sqlalchemy.orm import Session` at the top.

In `docu-intel/backend/app/parsers/image.py`, mirror the same setattr
block. The image parser only processes one page per call, so
`current_page_number = 1`.

- [ ] **Step 4.5: Run the cascade test**

Run: `cd docu-intel/backend && python -m pytest tests/test_cascading_attempt_logging.py -v`
Expected: PASS.

- [ ] **Step 4.6: Run the full backend test suite to make sure nothing else broke**

Run: `cd docu-intel/backend && python -m pytest -q -x`
Expected: all existing tests pass.

- [ ] **Step 4.7: Commit**

```bash
git add docu-intel/backend/app/ocr/cascading.py \
        docu-intel/backend/app/parsers/pdf.py \
        docu-intel/backend/app/parsers/image.py \
        docu-intel/backend/tests/test_cascading_attempt_logging.py
git commit -m "feat(ocr-cascade): log every tier attempt to OcrCascadeAttempt"
```

---

## Task 5: Timeline assembler (pure function)

**Files:**
- Create: `docu-intel/backend/app/services/ocr_flow_timeline.py`
- Test: `docu-intel/backend/tests/test_ocr_flow_timeline.py`

- [ ] **Step 5.1: Write the failing test**

```python
# docu-intel/backend/tests/test_ocr_flow_timeline.py
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from app.database.base import Base
from app.models.document import Document, DocumentPage, ExtractionJob
from app.models.ocr_cascade import OcrCascadeAttempt
from app.models.operations import IngestionEvent, WatchedFile
from app.services.ocr_flow_timeline import build_document_flow


def _make_session():
    from sqlalchemy import create_engine

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_build_document_flow_merges_jobs_and_events_and_pages_and_cascade():
    s = _make_session()
    doc = Document(
        id=1,
        original_filename="factura.pdf",
        file_hash="x" * 64,
        status="processed",
    )
    s.add(doc)
    s.flush()
    s.add_all([
        ExtractionJob(
            id=10, document_id=1, job_type="extract", status="finished",
            started_at=datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc),
            finished_at=datetime(2026, 1, 1, 10, 5, tzinfo=timezone.utc),
        ),
        IngestionEvent(
            id=100, event_type="watcher.detected", document_id=1,
            created_at=datetime(2026, 1, 1, 9, 59, tzinfo=timezone.utc),
        ),
        IngestionEvent(
            id=101, event_type="ingestion.committed", document_id=1,
            created_at=datetime(2026, 1, 1, 10, 0, 1, tzinfo=timezone.utc),
        ),
        DocumentPage(
            id=1000, document_id=1, page_number=1,
            ocr_engine="paddleocr", ocr_engine_version="3.0.0",
            ocr_confidence=0.91,
            processing_time_ms=1234,
        ),
        OcrCascadeAttempt(
            id=1, document_id=1, page_id=1000, page_number=1,
            tier="tesseract", tier_index=1, success=False, duration_ms=412,
            confidence=0.31, chars=5, reason="no_improvement",
            created_at=datetime(2026, 1, 1, 10, 0, 5, tzinfo=timezone.utc),
        ),
        OcrCascadeAttempt(
            id=2, document_id=1, page_id=1000, page_number=1,
            tier="paddleocr", tier_index=2, success=True, duration_ms=891,
            confidence=0.91, chars=421, reason="ok",
            created_at=datetime(2026, 1, 1, 10, 0, 6, tzinfo=timezone.utc),
        ),
    ])
    s.commit()

    steps = build_document_flow(s, document_id=1)
    kinds = [step["kind"] for step in steps]
    assert kinds[0] == "watcher.detected"
    assert kinds[-1] == "page.processed"
    assert any(k == "ingestion.committed" for k in kinds)
    assert any(k == "extraction_job" for k in kinds)
    # Steps are strictly ordered by timestamp.
    timestamps = [step["at"] for step in steps]
    assert timestamps == sorted(timestamps)
    # The page.processed step carries the full cascade trace.
    page_step = next(s for s in steps if s["kind"] == "page.processed")
    cascade = page_step["details"]["cascade_attempts"]
    assert [c["tier_index"] for c in cascade] == [1, 2]
    assert [c["tier"] for c in cascade] == ["tesseract", "paddleocr"]
    assert cascade[0]["success"] is False
    assert cascade[1]["success"] is True
```
    timestamps = [step["at"] for step in steps]
    assert timestamps == sorted(timestamps)
```

- [ ] **Step 5.2: Run the test to verify it fails**

Run: `cd docu-intel/backend && python -m pytest tests/test_ocr_flow_timeline.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 5.3: Implement the assembler**

```python
# docu-intel/backend/app/services/ocr_flow_timeline.py
"""Build the per-document historical timeline shown in the 'Flujo Documento' tab.

The timeline is assembled by reading three existing sources and merging them
by timestamp. We do **not** introduce a new table — the cascade is represented
at 'winning engine per page' granularity, which is what
``DocumentPage.ocr_engine`` already records.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.document import DocumentPage, ExtractionJob
from app.models.ocr_cascade import OcrCascadeAttempt
from app.models.operations import IngestionEvent


def build_document_flow(session: Session, *, document_id: int) -> list[dict[str, Any]]:
    """Return a chronologically ordered list of timeline steps for a document.

    Reads three existing sources plus the per-tier cascade log:

    * ``IngestionEvent`` — any event the watcher/parser emitted.
    * ``ExtractionJob`` — Celery job lifecycle.
    * ``DocumentPage`` — one row per page with the winning engine.
    * ``OcrCascadeAttempt`` — every tier tried per page. Attached to the
      matching ``page.processed`` step under
      ``details.cascade_attempts`` so the UI can render the full trace.
    """
    steps: list[dict[str, Any]] = []

    for ev in session.scalars(
        select(IngestionEvent).where(IngestionEvent.document_id == document_id)
    ).all():
        steps.append(
            {
                "kind": ev.event_type,
                "at": ev.created_at.isoformat() if ev.created_at else None,
                "details": ev.details_json or {},
                "error": ev.error_message,
            }
        )

    for job in session.scalars(
        select(ExtractionJob).where(ExtractionJob.document_id == document_id)
    ).all():
        at = job.started_at or job.finished_at
        steps.append(
            {
                "kind": "extraction_job",
                "at": at.isoformat() if at else None,
                "details": {
                    "job_id": job.id,
                    "job_type": job.job_type,
                    "status": job.status,
                    "started_at": job.started_at.isoformat() if job.started_at else None,
                    "finished_at": job.finished_at.isoformat() if job.finished_at else None,
                    "retries": job.retries,
                },
                "error": job.error_message,
            }
        )

    # One query for every page, then a single follow-up query for all
    # cascade attempts. Keeps the assembler O(1) round-trips regardless
    # of document size.
    pages = session.scalars(
        select(DocumentPage).where(DocumentPage.document_id == document_id)
    ).all()
    attempts_by_page: dict[int, list[OcrCascadeAttempt]] = {p.id: [] for p in pages}
    if pages:
        rows = session.scalars(
            select(OcrCascadeAttempt)
            .where(OcrCascadeAttempt.document_id == document_id)
            .order_by(
                OcrCascadeAttempt.page_id.asc(),
                OcrCascadeAttempt.tier_index.asc(),
            )
        ).all()
        for row in rows:
            attempts_by_page.setdefault(row.page_id, []).append(row)

    for page in pages:
        cascade_attempts = [
            {
                "id": a.id,
                "tier": a.tier,
                "tier_index": a.tier_index,
                "success": a.success,
                "duration_ms": a.duration_ms,
                "confidence": a.confidence,
                "chars": a.chars,
                "reason": a.reason,
                "error_message": a.error_message,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in attempts_by_page.get(page.id, [])
        ]
        steps.append(
            {
                "kind": "page.processed",
                "at": page.created_at.isoformat() if page.created_at else None,
                "details": {
                    "page_id": page.id,
                    "page_number": page.page_number,
                    "ocr_engine": page.ocr_engine,
                    "ocr_engine_version": page.ocr_engine_version,
                    "ocr_confidence": page.ocr_confidence,
                    "processing_time_ms": page.processing_time_ms,
                    "attempts": page.attempts,
                    "page_status": page.page_status,
                    "cascade_attempts": cascade_attempts,
                },
                "error": page.error_message,
            }
        )

    steps.sort(key=lambda s: s.get("at") or "")
    return steps


__all__ = ["build_document_flow"]
```

- [ ] **Step 5.4: Run the test to verify it passes**

Run: `cd docu-intel/backend && python -m pytest tests/test_ocr_flow_timeline.py -v`
Expected: PASS.

- [ ] **Step 5.5: Commit**

```bash
git add docu-intel/backend/app/services/ocr_flow_timeline.py docu-intel/backend/tests/test_ocr_flow_timeline.py
git commit -m "feat(ocr-flow): add timeline assembler for document flow"
```

---

## Task 6: REST + SSE endpoints

**Files:**
- Create: `docu-intel/backend/app/api/routes/ocr_flow.py`
- Test: `docu-intel/backend/tests/test_ocr_flow_endpoints.py`
- Modify: `docu-intel/backend/app/api/routes/__init__.py` (register router).

- [ ] **Step 6.1: Read existing admin router pattern**

Run: `head -60 docu-intel/backend/app/api/routes/admin_ocr_stats.py`
Note the auth dependency in use (likely `require_admin_or_gestor`). Reuse it exactly.

- [ ] **Step 6.2: Write the failing endpoint test**

```python
# docu-intel/backend/tests/test_ocr_flow_endpoints.py
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient


def _seed_doc_and_job():
    from app.database.base import Base
    from app.models.document import Document, ExtractionJob
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    s.add(Document(id=1, original_filename="a.pdf", file_hash="h", status="processing"))
    s.add(ExtractionJob(
        id=10, document_id=1, job_type="extract", status="started",
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    ))
    s.commit()
    return engine


def test_live_endpoint_returns_active_jobs(monkeypatch):
    from app.main import app  # type: ignore
    from app.api.deps import get_db  # type: ignore
    from app.services import ocr_flow_timeline  # noqa: F401

    engine = _seed_doc_and_job()

    def _override_db():
        from sqlalchemy.orm import sessionmaker
        Session = sessionmaker(bind=engine)
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _override_db
    client = TestClient(app)
    # Override auth dependency: assume the same pattern as admin_ocr_stats.
    from app.api.routes.admin_ocr_stats import require_admin_or_gestor  # type: ignore

    app.dependency_overrides[require_admin_or_gestor] = lambda: {"id": 1, "role": "admin"}
    response = client.get("/admin/ocr-flow/live")
    assert response.status_code == 200
    body = response.json()
    assert "jobs" in body
    assert any(j["document_id"] == 1 for j in body["jobs"])
```

- [ ] **Step 6.3: Run the test to verify it fails**

Run: `cd docu-intel/backend && python -m pytest tests/test_ocr_flow_endpoints.py -v`
Expected: FAIL with `404 Not Found` (route not registered yet).

- [ ] **Step 6.4: Implement the endpoints**

```python
# docu-intel/backend/app/api/routes/ocr_flow.py
"""OCR flow: live SSE stream + active-jobs snapshot + per-document timeline.

The snapshot endpoint is cheap (one SELECT against ``extraction_jobs`` filtered
to ``status IN ('pending','started')`` joined with ``documents``). The
per-document timeline reuses :func:`build_document_flow` from
``app.services.ocr_flow_timeline``. The SSE endpoint subscribes to the bus
defined in :mod:`app.services.events_bus` and streams one ``data: <json>``
frame per event.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.routes.admin_ocr_stats import require_admin_or_gestor  # type: ignore
from app.models.document import Document, ExtractionJob
from app.services.events_bus import subscribe_events
from app.services.ocr_flow_timeline import build_document_flow

logger = logging.getLogger("app.api.ocr_flow")

router = APIRouter()


@router.get("/admin/ocr-flow/live")
def get_live_jobs(
    db: Session = Depends(get_db),
    _user: dict = Depends(require_admin_or_gestor),
):
    rows = db.execute(
        select(ExtractionJob, Document.original_filename)
        .join(Document, Document.id == ExtractionJob.document_id)
        .where(ExtractionJob.status.in_(["pending", "started"]))
        .order_by(ExtractionJob.started_at.desc().nullslast())
        .limit(100)
    ).all()
    return {
        "jobs": [
            {
                "job_id": job.id,
                "document_id": job.document_id,
                "original_filename": filename,
                "job_type": job.job_type,
                "status": job.status,
                "started_at": job.started_at.isoformat() if job.started_at else None,
                "retries": job.retries,
                "error": job.error_message,
            }
            for job, filename in rows
        ]
    }


@router.get("/documents/{document_id}/flow")
def get_document_flow(
    document_id: int,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_admin_or_gestor),
):
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    return {
        "document_id": document_id,
        "original_filename": doc.original_filename,
        "status": doc.status,
        "steps": build_document_flow(db, document_id=document_id),
    }


@router.get("/admin/ocr-flow/stream")
async def stream_events(
    request: Request,
    _user: dict = Depends(require_admin_or_gestor),
):
    """Server-Sent Events stream of OCR flow lifecycle events."""

    async def event_source() -> AsyncIterator[dict]:
        async for envelope in subscribe_events("ocr_flow"):
            if await request.is_disconnected():
                return
            yield {"event": envelope.get("type", "message"), "data": json.dumps(envelope)}

    return _sse_response(event_source())


def _sse_response(events: AsyncIterator[dict]):
    # Lazy import so unit tests that don't exercise the stream don't need sse-starlette.
    from sse_starlette.sse import EventSourceResponse

    async def _wrapper():
        async for evt in events:
            yield evt

    return EventSourceResponse(_wrapper())


__all__ = ["router"]
```

- [ ] **Step 6.5: Register the router**

In `docu-intel/backend/app/api/routes/__init__.py`, append the import + include:

```python
from app.api.routes import ocr_flow  # noqa: F401
...
api_router.include_router(ocr_flow.router, tags=["ocr-flow"])
```

(Adjust the import/include lines to match the existing style in the file — find the closest precedent and mirror it.)

- [ ] **Step 6.6: Run the endpoint test**

Run: `cd docu-intel/backend && python -m pytest tests/test_ocr_flow_endpoints.py -v`
Expected: PASS.

- [ ] **Step 6.7: Commit**

```bash
git add docu-intel/backend/app/api/routes/ocr_flow.py docu-intel/backend/app/api/routes/__init__.py docu-intel/backend/tests/test_ocr_flow_endpoints.py
git commit -m "feat(api): expose OCR flow live snapshot, timeline and SSE stream"
```

---

## Task 7: Frontend — API client + types

**Files:**
- Create: `docu-intel/frontend/src/api/ocrFlow.ts`
- Modify: `docu-intel/frontend/src/types/api.ts` (add two interfaces).

- [ ] **Step 7.1: Add types**

Open `docu-intel/frontend/src/types/api.ts`. Append at the bottom (just before the closing of the existing namespace / export list):

```typescript
export interface OcrFlowLiveJob {
  job_id: number
  document_id: number
  original_filename: string
  job_type: string
  status: string
  started_at: string | null
  retries: number
  error: string | null
}

export interface OcrFlowDocumentStep {
  kind: string
  at: string | null
  details: Record<string, unknown>
  error: string | null
}

export interface OcrCascadeAttempt {
  id: number
  document_id: number
  page_id: number
  page_number: number
  tier: string
  tier_index: number
  success: boolean
  duration_ms: number
  confidence: number | null
  chars: number
  reason: string | null
  error_message: string | null
  created_at: string
}
```

- [ ] **Step 7.2: Read existing API client conventions**

Run: `head -40 docu-intel/frontend/src/api/client.ts`
Note the base URL helper, the `api.<resource>()` function style and the auth header pattern. Reuse them.

- [ ] **Step 7.3: Create the client module**

```typescript
// docu-intel/frontend/src/api/ocrFlow.ts
import type { OcrFlowLiveJob, OcrFlowDocumentStep } from "@/types/api"

import { apiGet, buildStreamUrl, withJson } from "./client"

interface OcrFlowLiveResponse {
  jobs: OcrFlowLiveJob[]
}

interface OcrFlowDocumentResponse {
  document_id: number
  original_filename: string
  status: string
  steps: OcrFlowDocumentStep[]
}

export function fetchOcrFlowLive() {
  return apiGet<OcrFlowLiveResponse>("/admin/ocr-flow/live")
}

export function fetchOcrFlowDocument(documentId: number) {
  return apiGet<OcrFlowDocumentResponse>(`/documents/${documentId}/flow`)
}

export function ocrFlowStreamUrl() {
  return buildStreamUrl("/admin/ocr-flow/stream")
}
```

> If `apiGet` / `buildStreamUrl` / `withJson` are not the exact names exported
> by `client.ts`, adjust to the real ones. The intent is: a JSON `GET`
> helper, a helper that returns the absolute SSE URL, and a JSON content-type
> helper. The two test tasks below (Step 7.4) only assert shape; they do not
> depend on the helper names.

- [ ] **Step 7.4: Smoke typecheck**

Run: `cd docu-intel/frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 7.5: Commit**

```bash
git add docu-intel/frontend/src/api/ocrFlow.ts docu-intel/frontend/src/types/api.ts
git commit -m "feat(frontend): add OCR flow api client and types"
```

---

## Task 8: Frontend — SSE hook into TanStack Query

**Files:**
- Create: `docu-intel/frontend/src/hooks/useOcrFlowStream.ts`

- [ ] **Step 8.1: Write a minimal test of the merge logic (no DOM)**

```typescript
// docu-intel/frontend/src/hooks/useOcrFlowStream.test.ts
import { describe, expect, it } from "vitest"

import { mergeOcrFlowEvent } from "./useOcrFlowStream"

describe("mergeOcrFlowEvent", () => {
  it("appends a started job to the live list", () => {
    const next = mergeOcrFlowEvent(
      { jobs: [{ job_id: 1, document_id: 1, status: "started" } as never] },
      { type: "job.started", task_id: "t1", document_id: 1, task: "app.workers.tasks.extract_document" },
    )
    expect(next.jobs.some((j) => j.document_id === 1)).toBe(true)
  })

  it("removes a job when it transitions to finished", () => {
    const next = mergeOcrFlowEvent(
      {
        jobs: [
          { job_id: 1, document_id: 1, status: "started" } as never,
          { job_id: 2, document_id: 2, status: "started" } as never,
        ],
      },
      { type: "job.finished", task_id: "t1", document_id: 1, state: "SUCCESS" },
    )
    expect(next.jobs).toHaveLength(1)
    expect(next.jobs[0].document_id).toBe(2)
  })
})
```

- [ ] **Step 8.2: Run the test to verify it fails**

Run: `cd docu-intel/frontend && npx vitest run src/hooks/useOcrFlowStream.test.ts`
Expected: FAIL with `Cannot find module`.

- [ ] **Step 8.3: Implement the hook + helper**

```typescript
// docu-intel/frontend/src/hooks/useOcrFlowStream.ts
import { useEffect } from "react"
import { useQueryClient } from "@tanstack/react-query"

import type { OcrFlowLiveJob } from "@/types/api"

import { ocrFlowStreamUrl } from "@/api/ocrFlow"

export const OCR_FLOW_LIVE_KEY = ["ocr-flow", "live"] as const

interface OcrFlowLiveSnapshot {
  jobs: OcrFlowLiveJob[]
}

interface OcrFlowEvent {
  type: string
  task?: string
  task_id?: string
  document_id?: number
  state?: string
  error?: string
  runtime_s?: number
}

/**
 * Pure reducer-style helper exposed for unit tests.
 *
 * Returns a *new* snapshot so React Query's referential equality check picks
 * the change up and re-renders subscribers.
 */
export function mergeOcrFlowEvent(
  snapshot: OcrFlowLiveSnapshot,
  event: OcrFlowEvent,
): OcrFlowLiveSnapshot {
  if (event.type === "job.finished" || event.type === "job.failed") {
    return {
      jobs: snapshot.jobs.filter(
        (job) => job.document_id !== event.document_id || job.job_id === undefined,
      ),
    }
  }
  if (event.type === "job.started" || event.type === "job.queued") {
    const placeholder: OcrFlowLiveJob = {
      job_id: 0,
      document_id: event.document_id ?? 0,
      original_filename: "(iniciando…)",
      job_type: event.task?.split(".").pop() ?? "extract",
      status: event.type === "job.queued" ? "pending" : "started",
      started_at: new Date().toISOString(),
      retries: 0,
      error: null,
    }
    return {
      jobs: [
        placeholder,
        ...snapshot.jobs.filter((job) => job.document_id !== placeholder.document_id),
      ],
    }
  }
  return snapshot
}

export function useOcrFlowStream() {
  const queryClient = useQueryClient()
  useEffect(() => {
    if (typeof window === "undefined" || typeof EventSource === "undefined") {
      return
    }
    const source = new EventSource(ocrFlowStreamUrl(), { withCredentials: true })
    const handler = (event: MessageEvent) => {
      try {
        const parsed = JSON.parse(event.data) as OcrFlowEvent
        queryClient.setQueryData<OcrFlowLiveSnapshot>(OCR_FLOW_LIVE_KEY, (prev) =>
          mergeOcrFlowEvent(prev ?? { jobs: [] }, parsed),
        )
      } catch {
        // ignore malformed events
      }
    }
    source.onmessage = handler
    source.onerror = () => {
      // The browser will auto-reconnect; nothing to do.
    }
    return () => {
      source.close()
    }
  }, [queryClient])
}
```

> The `withCredentials: true` flag assumes the SSE endpoint uses the same
> auth cookie/header as the rest of the API. If the existing admin endpoints
> rely on `Authorization: Bearer …` headers (EventSource cannot set custom
> headers), the SSE endpoint must accept the auth via a cookie or a `?token=`
> query parameter. Mirror whatever the existing WebSocket / streaming
> endpoints in this repo do; if there are none, prefer the cookie path.

- [ ] **Step 8.4: Run the test to verify it passes**

Run: `cd docu-intel/frontend && npx vitest run src/hooks/useOcrFlowStream.test.ts`
Expected: PASS.

- [ ] **Step 8.5: Commit**

```bash
git add docu-intel/frontend/src/hooks/useOcrFlowStream.ts docu-intel/frontend/src/hooks/useOcrFlowStream.test.ts
git commit -m "feat(frontend): add SSE hook for OCR flow live updates"
```

---

## Task 9: Frontend — data hooks (snapshot + timeline)

**Files:**
- Create: `docu-intel/frontend/src/pages/admin/useAdminOcrFlowData.ts`
- Create: `docu-intel/frontend/src/pages/admin/useAdminOcrFlowData.test.ts`

- [ ] **Step 9.1: Write the test**

```typescript
// docu-intel/frontend/src/pages/admin/useAdminOcrFlowData.test.ts
import { describe, expect, it } from "vitest"

import { ocrFlowLiveQueryKey, ocrFlowDocumentQueryKey } from "./useAdminOcrFlowData"

describe("query keys", () => {
  it("live key is stable", () => {
    expect(ocrFlowLiveQueryKey()).toEqual(["ocr-flow", "live"])
  })
  it("document key includes the document id", () => {
    expect(ocrFlowDocumentQueryKey(42)).toEqual(["ocr-flow", "document", 42])
  })
})
```

- [ ] **Step 9.2: Run the test to verify it fails**

Run: `cd docu-intel/frontend && npx vitest run src/pages/admin/useAdminOcrFlowData.test.ts`
Expected: FAIL with `Cannot find module`.

- [ ] **Step 9.3: Implement the hooks**

```typescript
// docu-intel/frontend/src/pages/admin/useAdminOcrFlowData.ts
import { useQuery } from "@tanstack/react-query"

import { fetchOcrFlowDocument, fetchOcrFlowLive } from "@/api/ocrFlow"
import { OCR_FLOW_LIVE_KEY, useOcrFlowStream } from "@/hooks/useOcrFlowStream"

export function ocrFlowLiveQueryKey() {
  return OCR_FLOW_LIVE_KEY
}

export function ocrFlowDocumentQueryKey(documentId: number) {
  return ["ocr-flow", "document", documentId] as const
}

export function useOcrFlowLive() {
  useOcrFlowStream()
  return useQuery({
    queryKey: ocrFlowLiveQueryKey(),
    queryFn: () => fetchOcrFlowLive(),
    refetchOnWindowFocus: false,
  })
}

export function useOcrFlowDocument(documentId: number | null) {
  return useQuery({
    queryKey: documentId ? ocrFlowDocumentQueryKey(documentId) : ["ocr-flow", "document", "none"],
    queryFn: () => fetchOcrFlowDocument(documentId as number),
    enabled: documentId !== null,
  })
}
```

- [ ] **Step 9.4: Run the test to verify it passes**

Run: `cd docu-intel/frontend && npx vitest run src/pages/admin/useAdminOcrFlowData.test.ts`
Expected: PASS.

- [ ] **Step 9.5: Commit**

```bash
git add docu-intel/frontend/src/pages/admin/useAdminOcrFlowData.ts docu-intel/frontend/src/pages/admin/useAdminOcrFlowData.test.ts
git commit -m "feat(frontend): add query hooks for OCR flow data"
```

---

## Task 10: Frontend — UI (tabs + table + timeline)

**Files:**
- Create: `docu-intel/frontend/src/pages/admin/AdminOcrFlowTab.tsx`
- Create: `docu-intel/frontend/src/pages/admin/AdminOcrFlowTab.test.tsx`
- Create: `docu-intel/frontend/src/pages/admin/AdminOcrFlowRoute.tsx`
- Modify: `docu-intel/frontend/src/routes/router.tsx`
- Modify: `docu-intel/frontend/src/routes/adminTabs.ts`
- Modify: `docu-intel/frontend/src/components/layout/Sidebar.tsx`

- [ ] **Step 10.1: Add the new admin tab to the registry**

In `docu-intel/frontend/src/routes/adminTabs.ts`, append:

```typescript
{
  key: "flujo-ocr",
  path: "/admin/flujo-ocr",
  label: "Flujo OCR",
  icon: "activity", // or the lucide icon name used by the other entries
  component: () => import("@/pages/admin/AdminOcrFlowRoute"),
  roles: ["admin", "gestor"],
}
```

(Adjust the icon name to match the existing convention. Verify by reading
the file: `cat docu-intel/frontend/src/routes/adminTabs.ts`.)

- [ ] **Step 10.2: Add the sidebar link**

In `docu-intel/frontend/src/components/layout/Sidebar.tsx`, inside the
existing admin group (find the `NAV_GROUPS` array), add:

```typescript
{ to: "/admin/flujo-ocr", label: "Flujo OCR", icon: "Activity", roles: ["admin", "gestor"] },
```

(Match the entry shape used by the other admin links. The roles array is
filtered by `PermissionGate` per F2.)

- [ ] **Step 10.3: Create the route entry**

```typescript
// docu-intel/frontend/src/pages/admin/AdminOcrFlowRoute.tsx
import { AdminOcrFlowTab } from "./AdminOcrFlowTab"

export default function AdminOcrFlowRoute() {
  return <AdminOcrFlowTab />
}
```

- [ ] **Step 10.4: Create the page component**

```tsx
// docu-intel/frontend/src/pages/admin/AdminOcrFlowTab.tsx
import { useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Breadcrumbs } from "@/components/layout/Breadcrumbs"
import { PageHeader } from "@/components/layout/PageHeader"
import { StatusBadge } from "@/components/layout/StatusBadge"
import { useOcrFlowDocument, useOcrFlowLive } from "./useAdminOcrFlowData"
import { formatDate } from "@/lib/utils"

const STEP_LABELS: Record<string, string> = {
  "watcher.detected": "Detectado en watcher",
  "ingestion.committed": "Ingerido en BD",
  "extraction_job": "Job de extracción",
  "page.processed": "Página procesada",
}

const ENGINE_LABELS: Record<string, string> = {
  paddleocr: "PaddleOCR",
  pymupdf: "PyMuPDF",
  ppstructure: "PP-Structure",
  dotsmocr: "Dots MOCR",
  empty: "Sin OCR",
}

export function AdminOcrFlowTab() {
  const [activeDocumentId, setActiveDocumentId] = useState<number | null>(null)
  const live = useOcrFlowLive()
  const docFlow = useOcrFlowDocument(activeDocumentId)

  return (
    <>
      <Breadcrumbs items={[{ label: "Administración" }, { label: "Flujo OCR" }]} />
      <PageHeader
        title="Flujo OCR"
        description="Visualización en directo y por documento del recorrido de cada archivo por el pipeline."
      />

      <Tabs defaultValue="live">
        <TabsList>
          <TabsTrigger value="live">En directo</TabsTrigger>
          <TabsTrigger value="document">Por documento</TabsTrigger>
        </TabsList>

        <TabsContent value="live" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Jobs activos</CardTitle>
              <CardDescription>
                {live.data?.jobs.length ?? 0} job(s) en cola o ejecución. Se actualiza vía SSE.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Documento</TableHead>
                    <TableHead>Tipo</TableHead>
                    <TableHead>Estado</TableHead>
                    <TableHead>Inicio</TableHead>
                    <TableHead>Reintentos</TableHead>
                    <TableHead className="text-right">Acción</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(live.data?.jobs ?? []).map((job) => (
                    <TableRow key={`${job.job_id}-${job.document_id}`}>
                      <TableCell className="font-medium">
                        {job.original_filename}
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline">{job.job_type}</Badge>
                      </TableCell>
                      <TableCell>
                        <StatusBadge status={job.status} />
                      </TableCell>
                      <TableCell className="text-muted-foreground text-xs">
                        {job.started_at ? formatDate(job.started_at) : "—"}
                      </TableCell>
                      <TableCell>{job.retries}</TableCell>
                      <TableCell className="text-right">
                        <button
                          className="text-sm text-primary underline-offset-2 hover:underline"
                          onClick={() => setActiveDocumentId(job.document_id)}
                        >
                          Ver flujo
                        </button>
                      </TableCell>
                    </TableRow>
                  ))}
                  {!(live.data?.jobs ?? []).length ? (
                    <TableRow>
                      <TableCell colSpan={6} className="h-24 text-center text-muted-foreground">
                        No hay jobs en ejecución. Sube un documento o espera a que el watcher detecte uno nuevo.
                      </TableCell>
                    </TableRow>
                  ) : null}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="document" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Flujo del documento</CardTitle>
              <CardDescription>
                {activeDocumentId
                  ? `Línea de tiempo histórica del documento #${activeDocumentId}.`
                  : "Selecciona un documento desde la pestaña 'En directo' para ver su línea de tiempo."}
              </CardDescription>
            </CardHeader>
            <CardContent>
              {activeDocumentId ? (
                <ol className="space-y-3">
                  {(docFlow.data?.steps ?? []).map((step, idx) => (
                    <li className="rounded-md border p-3" key={`${step.kind}-${idx}`}>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-semibold">
                          {STEP_LABELS[step.kind] ?? step.kind}
                        </span>
                        {step.kind === "page.processed" && step.details.ocr_engine ? (
                          <Badge variant="outline">
                            {ENGINE_LABELS[String(step.details.ocr_engine)] ??
                              String(step.details.ocr_engine)}
                          </Badge>
                        ) : null}
                        {typeof step.details.ocr_confidence === "number" ? (
                          <Badge variant="secondary">
                            {Math.round(Number(step.details.ocr_confidence) * 100)}% confianza
                          </Badge>
                        ) : null}
                        <span className="ml-auto text-xs text-muted-foreground">
                          {step.at ? formatDate(step.at) : "—"}
                        </span>
                      </div>

                      {/* Cascade trace: every tier tried for this page.
                          ``step.details.cascade_attempts`` is an array of
                          ``OcrCascadeAttempt`` (sorted by tier_index) when
                          the assembler picked them up; the per-page row
                          above remains the "winner" summary. */}
                      {Array.isArray(step.details.cascade_attempts) &&
                      (step.details.cascade_attempts as Array<Record<string, unknown>>).length > 0 ? (
                        <ol className="mt-2 space-y-1 border-l-2 pl-3 text-xs">
                          {(
                            step.details.cascade_attempts as Array<Record<string, unknown>>
                          ).map((attempt) => {
                            const tier = String(attempt.tier ?? "unknown")
                            const dur = Number(attempt.duration_ms ?? 0)
                            const ok = Boolean(attempt.success)
                            const conf =
                              typeof attempt.confidence === "number"
                                ? Math.round(Number(attempt.confidence) * 100)
                                : null
                            return (
                              <li className="flex flex-wrap items-center gap-2" key={String(attempt.id)}>
                                <span className="font-mono text-muted-foreground">
                                  T{Number(attempt.tier_index)}
                                </span>
                                <span className="font-medium">
                                  {ENGINE_LABELS[tier] ?? tier}
                                </span>
                                <Badge variant={ok ? "success" : "destructive"}>
                                  {ok ? "✓" : "✗"} {dur} ms
                                </Badge>
                                {conf !== null ? (
                                  <span className="text-muted-foreground">{conf}% conf</span>
                                ) : null}
                                {attempt.reason && attempt.reason !== "ok" ? (
                                  <span className="text-muted-foreground">
                                    · {String(attempt.reason)}
                                  </span>
                                ) : null}
                                {attempt.error_message ? (
                                  <span className="text-destructive">
                                    · {String(attempt.error_message)}
                                  </span>
                                ) : null}
                              </li>
                            )
                          })}
                        </ol>
                      ) : null}

                      {step.error ? (
                        <p className="mt-2 text-sm text-destructive">Error: {step.error}</p>
                      ) : null}
                    </li>
                  ))}
                </ol>
              ) : (
                <p className="text-sm text-muted-foreground">
                  Sin documento seleccionado.
                </p>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </>
  )
}
```

- [ ] **Step 10.5: Smoke test the page**

```tsx
// docu-intel/frontend/src/pages/admin/AdminOcrFlowTab.test.tsx
import { describe, expect, it, vi } from "vitest"
import { render, screen, fireEvent } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

import { AdminOcrFlowTab } from "./AdminOcrFlowTab"

vi.mock("./useAdminOcrFlowData", () => ({
  useOcrFlowLive: () => ({
    data: {
      jobs: [
        {
          job_id: 1,
          document_id: 42,
          original_filename: "factura.pdf",
          job_type: "extract",
          status: "started",
          started_at: new Date().toISOString(),
          retries: 0,
          error: null,
        },
      ],
    },
  }),
  useOcrFlowDocument: () => ({ data: { steps: [] } }),
}))

describe("AdminOcrFlowTab", () => {
  it("shows the two tabs and switches to the document timeline on click", () => {
    const client = new QueryClient()
    render(
      <QueryClientProvider client={client}>
        <AdminOcrFlowTab />
      </QueryClientProvider>,
    )
    expect(screen.getByRole("tab", { name: "En directo" })).toBeInTheDocument()
    expect(screen.getByRole("tab", { name: "Por documento" })).toBeInTheDocument()
    fireEvent.click(screen.getByText("Ver flujo"))
    expect(screen.getByText(/Línea de tiempo histórica del documento #42/)).toBeInTheDocument()
  })
})
```

- [ ] **Step 10.6: Run the test**

Run: `cd docu-intel/frontend && npx vitest run src/pages/admin/AdminOcrFlowTab.test.tsx`
Expected: PASS.

- [ ] **Step 10.7: Typecheck + build**

Run: `cd docu-intel/frontend && npx tsc --noEmit && npm run build`
Expected: no errors, build succeeds.

- [ ] **Step 10.8: Commit**

```bash
git add docu-intel/frontend/src/pages/admin/AdminOcrFlowTab.tsx \
        docu-intel/frontend/src/pages/admin/AdminOcrFlowTab.test.tsx \
        docu-intel/frontend/src/pages/admin/AdminOcrFlowRoute.tsx \
        docu-intel/frontend/src/routes/router.tsx \
        docu-intel/frontend/src/routes/adminTabs.ts \
        docu-intel/frontend/src/components/layout/Sidebar.tsx
git commit -m "feat(frontend): add OCR flow admin page with live and document tabs"
```

---

## Task 11: End-to-end verification

**Files:** none (manual verification).

- [ ] **Step 11.1: Backend test suite is green**

Run: `cd docu-intel/backend && python -m pytest -q`
Expected: all tests pass; the new tests for `events_bus`, `ocr_cascade_model`, `cascading_attempt_logging`, `ocr_flow_timeline` and `ocr_flow_endpoints` are included.

- [ ] **Step 11.2: Frontend test suite is green**

Run: `cd docu-intel/frontend && npm test -- --run`
Expected: all tests pass; the new `useOcrFlowStream` and `AdminOcrFlowTab` tests are included.

- [ ] **Step 11.3: Manual smoke**

1. `cd docu-intel && docker compose up --build`
2. Open `http://localhost:5173/admin/flujo-ocr`.
3. In a separate tab, drop a PDF into `data/input/facturas`. Watch the row appear in "En directo" within ~1s. Click "Ver flujo". Switch to "Por documento" and confirm the timeline lists:
   - watcher → ingestion → extraction_job → **cascade** → page.processed.
   - The cascade step shows every tier tried, with success/fail and duration (e.g. `Tesseract 412ms ❌ quality → PaddleOCR 891ms ✓`).

- [ ] **Step 11.4: No stray type/lint warnings**

Run: `cd docu-intel/frontend && npx tsc --noEmit && (npm run lint || true)`
Expected: no errors, warnings are pre-existing.

- [ ] **Step 11.5: Final commit (changelog/docstring if needed)**

```bash
git add -A
git commit --allow-empty -m "docs(ocr-flow): verified end-to-end live and historical timeline"
```

---

## Self-Review

- **Spec coverage**
  - "Apartado visual" → Task 10 (`AdminOcrFlowTab`).
  - "En directo" → Task 2 (Celery signals), Task 6 (SSE endpoint), Task 8 (EventSource hook), Task 9 (live query).
  - "Historial" → Task 5 (assembler), Task 6 (`/documents/{id}/flow`), Task 9 (`useOcrFlowDocument`), Task 10 (timeline render).
  - "Por donde han pasado y los datos" → Task 10 renders `engine`, `confidence`, `processing_time_ms`, `attempts`, `error`, `retries` and the human-readable step label.
  - **Cascade per-tier trace** (new requirement) → Task 3 (model + migration), Task 4 (instrument cascade), Task 5 (assembler reads attempts), Task 10 (UI shows the chain `Tesseract 412ms ❌ → PaddleOCR 891ms ✓`).
  - Permissions: route lives under `/admin/*` so it inherits the existing admin/gestor gate (F2 already wired).
  - Code-splitting: lazy import in `router.tsx` (per F1/F4).

- **Placeholder scan**
  - No "TBD" / "TODO" / "implement later".
  - Every code step shows the actual snippet.
  - Tests are concrete, not "similar to task N".

- **Type consistency**
  - `OcrFlowLiveJob`, `OcrFlowDocumentStep`, `OcrCascadeAttempt` defined in Task 7.1 and used in Task 7.3, 8.3, 9.3, 10.4 → consistent.
  - `OCR_FLOW_LIVE_KEY` defined in Task 8.3, re-exported in Task 9.3, used by the SSE merge → consistent.
  - Endpoint paths `/admin/ocr-flow/live`, `/admin/ocr-flow/stream`, `/documents/{document_id}/flow` appear identically in backend (Task 6) and frontend (Task 7) → consistent.
  - `OcrCascadeAttempt` columns (`tier`, `tier_index`, `success`, `duration_ms`, `confidence`, `chars`, `reason`, `error_message`) referenced identically by the model (Task 3), the cascade recorder (Task 4), the timeline assembler (Task 5) and the UI (Task 10) → consistent.

- **Open question for executor**
  - The `EventSource` browser API cannot set custom `Authorization` headers. If the existing admin auth model is header-based (not cookie-based), the SSE endpoint in Task 6 must accept a `?token=…` query param OR a cookie. **Verify by reading `app/api/routes/admin_ocr_stats.py` before executing Task 6.4** and adjust `_sse_response`'s dependency wiring if needed. The dependency on `require_admin_or_gestor` is the only check; how the token reaches it is the existing API's job.

- **Critical pre-execution fixes (must apply, not optional)**
  1. **SSE auth via query token.** Confirmed: this repo authenticates everything with `Authorization: Bearer …` (see `frontend/src/api/core.ts`); there is no session cookie. `EventSource` cannot send that header, so the SSE endpoint **must** accept the token as `?token=…`. The browser will append it automatically when the hook calls `new EventSource(ocrFlowStreamUrl() + "?token=" + bearer)`. The endpoint must validate it via a small wrapper dependency that calls the same auth check the header would.
  2. **Add `task_prerun` signal.** `before_task_publish` fires when the producer enqueues — it does **not** mean the task actually started. Add a `task_prerun` handler so we get a guaranteed `job.started` when the worker picks the task up. Without this, a job that is enqueued but never picked up would stay "pending" forever in the live view.
  3. **Use a sync Redis client in Celery signals.** The current bus uses `redis.asyncio` (works inside the FastAPI request loop). Celery signal handlers run in worker processes, sync by default with prefork. Mixing `asyncio.run(...)` inside a signal works in prefork but breaks under `gevent`/`eventlet`. Either (a) confirm the worker pool is prefork and keep `asyncio.run` (acceptable), or (b) introduce a sync `redis` client just for the publisher side of the bus.
  4. **Frontend fallback polling.** If the SSE connection drops, `EventSource` auto-reconnects, but the live view should also re-fetch the snapshot every 5s as a safety net. Add `refetchInterval: 5_000` to `useOcrFlowLive`.
  5. **Test the failing endpoint with the right `get_db` import.** The test in Task 6.2 imports `app.api.deps.get_db`; the real one is `app.database.session.get_db` (used in `admin_ocr_stats.py`). Mirror the real import path.
  6. **Frontend client shape.** `api/core.ts` exports `request(...)` and helpers, and the per-resource modules (`admin.ts`, `documents.ts`) spread into a single `api` object. Add `api.ocrFlowLive()`, `api.ocrFlowDocument(id)`, and an SSE-URL builder in a new `api/ocrFlow.ts` — do not invent `apiGet`/`buildStreamUrl` helpers.
  7. **`adminTabs.ts` does not carry `component`.** It is metadata only. Add the route in `router.tsx` (lazy import per F4) and optionally extend `ADMIN_TABS` with an entry for the sidebar link. The plan's Task 10.1 needs rewriting to match this shape.
  8. **Cascade recorder failure isolation.** The recorder closure in `parsers/pdf.py` and `parsers/image.py` **must** catch all exceptions (`db.rollback` on failure) so an OCR run never dies because the cascade log table is unavailable. The `_record_attempt` helper in `cascading.py` also wraps in `try/except`. The unit test in Task 4.1 uses `cascade.attempt_recorder = ...` directly; **add a second test that verifies a recorder that raises does not propagate the exception** (the test should mock the recorder to raise and assert `cascade.extract` still returns the primary result).
  9. **Verify the parser-side context injection.** In Task 4.4, the `setattr` on `ocr_engine` uses the parser's `document_id` / `page_id` / `page_number`. Read `parsers/pdf.py` lines 600-700 carefully before editing — the `page` variable may not always have `.id` populated yet at that point in the loop. The injection point must be **after** the `DocumentPage` row is created and `s.flush()` is called; otherwise `current_page_id` is `None` and the recorder silently no-ops. Confirm by reading the file and adjust the injection point accordingly.
  10. **`get_ocr_engine_class()` returns a fresh instance per call.** The cascade is built **per page** in the existing parser, so the `setattr` hook in Task 4.4 is fine (no shared state). If the parser ever caches the cascade across pages, the setattr must move inside the per-page loop — verify by reading the parser's flow.
