"""Final import + structure smoke for the OCR flow stack."""


def test_all_new_imports_resolve():
    from app.services.events_bus import (
        publish_event,
        publish_event_sync,
        subscribe_events,
        InMemoryBus,
        RedisBus,
        Bus,
        CHANNEL,
    )
    from app.models.ocr_cascade import OcrCascadeAttempt
    from app.models import OcrCascadeAttempt as A2
    from app.services.ocr_flow_timeline import build_document_flow
    from app.api.routes.ocr_flow import router
    from app.api.deps import get_current_user
    from app.workers.celery_app import celery_app

    assert OcrCascadeAttempt is A2
    assert CHANNEL == "ocr_flow"
    assert router is not None
    assert callable(publish_event)
    assert callable(publish_event_sync)
    assert callable(subscribe_events)
    assert celery_app.main == "docuintel"


def test_router_exposes_three_paths():
    from app.api.routes.ocr_flow import router

    paths = sorted({r.path for r in router.routes})
    assert "/admin/ocr-flow/live" in paths
    assert "/admin/ocr-flow/stream" in paths
    assert "/documents/{document_id}/flow" in paths


def test_inmemory_bus_round_trip():
    """A second sanity check that the bus still works end-to-end."""
    import asyncio

    from app.services.events_bus import InMemoryBus

    async def _go():
        bus = InMemoryBus()
        iterator = bus.subscribe()
        consumer = asyncio.create_task(iterator.__anext__())
        await asyncio.sleep(0)
        await bus.publish("test.event", {"x": 1})
        return await asyncio.wait_for(consumer, timeout=1.0)

    result = asyncio.run(_go())
    assert result == {"type": "test.event", "x": 1}
