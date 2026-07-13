from app.api.routes.ai import _with_status_elapsed


def test_status_frame_gets_elapsed_time_without_changing_safe_fields():
    frame = b'event: status\ndata: {"state": "retrieval", "cache_hit": false}\n\n'

    enriched = _with_status_elapsed(frame, 123.456)

    assert b'"state": "retrieval"' in enriched
    assert b'"cache_hit": false' in enriched
    assert b'"elapsed_ms": 123.5' in enriched


def test_non_status_sse_frame_is_unchanged():
    frame = b'event: delta\ndata: {"text": "respuesta"}\n\n'

    assert _with_status_elapsed(frame, 10) == frame
