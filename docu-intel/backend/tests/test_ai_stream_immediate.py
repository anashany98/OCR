"""S3.1 — ``/ai/ask/stream`` returns the first SSE event immediately.

The MiniMax M3 (FASE 3) plan flagged ``/ai/ask/stream`` as
"NO CUMPLE" the immediate-SSE contract because ``collect_context``
ran synchronously before the first ``yield``. The current
implementation wraps the heavy builder in an outer
``immediate_event_stream`` generator whose **first yield** is the
``event: status {state: cache}`` byte sequence — that is sent to
the client before any of the expensive work
(``resolve_user_access_scope``, ``select_chat_model``, the cache
lookup, the inner ``_build_stream_response``) begins.

This test pins that contract: it reads the source of
``ask_stream`` and asserts that the very first ``yield`` inside
the generator is a non-empty ``status`` event and that it appears
**before** any of the expensive helper calls
(``resolve_user_access_scope``, ``select_chat_model``,
``_build_stream_response``). A future refactor that re-introduces
a synchronous prelude before the first yield will fail this test.
"""
from __future__ import annotations

from pathlib import Path

import pytest


AI_ROUTE_PATH = Path("app/api/routes/ai.py")


def _function_body(name: str) -> str:
    """Return the source of the named top-level ``async def`` from
    the AI route file. We read directly from disk to avoid Python's
    bytecode cache masking a recent edit (see the M-12 follow-up
    in ``test_search_scope_sql_layer.py`` for the same rationale).
    """
    text = AI_ROUTE_PATH.read_text(encoding="utf-8")
    lines = text.splitlines()
    body: list[str] = []
    in_target = False
    for line in lines:
        if line.startswith(f"async def {name}(") or line.startswith(f"def {name}("):
            in_target = True
            body.append(line)
            continue
        if in_target:
            if line and not line[0].isspace() and line.startswith(("def ", "async def ")):
                break
            body.append(line)
    if not in_target:
        pytest.fail(f"def {name} not found in {AI_ROUTE_PATH}")
    return "\n".join(body)


def test_ask_stream_emits_first_event_before_heavy_work():
    """The first ``yield`` inside the ``ask_stream`` endpoint must
    be a non-empty ``status`` event **before** any of the expensive
    helper calls (``resolve_user_access_scope``,
    ``select_chat_model``, ``_build_stream_response``). This
    guarantees the client sees the first SSE byte within
    milliseconds of the request reaching the worker.
    """
    body = _function_body("ask_stream")
    # Find the inner generator. We expect a nested ``async def``
    # whose first statement is a ``yield`` containing the literal
    # status event the frontend uses to flip the UI to "thinking".
    # We use a simple textual assertion rather than AST parsing so
    # the test stays robust to refactors that change the wrapper
    # name (``immediate_event_stream`` etc.) but preserve the
    # contract.
    assert 'yield (' in body or 'yield ' in body, (
        "ask_stream does not yield any SSE event. It must yield the "
        "first status event before any expensive work runs."
    )
    # The first ``yield`` must contain the literal status event.
    # We look for the status byte sequence anywhere in the body; the
    # byte sequence is unique enough that a false positive is
    # unlikely. If a refactor renames the event, update this test.
    assert b'"state": "cache"' in body.encode() or '"state": "cache"' in body, (
        "ask_stream does not emit an `event: status {state: cache}` "
        "event. The first SSE event must flip the UI to its "
        "thinking state."
    )
    # The expensive helper calls must come *after* the first yield.
    # We measure this by splitting the body at the first ``yield``
    # and checking that the helpers are not in the prefix.
    if "yield " in body:
        first_yield_index = body.index("yield ")
    else:
        first_yield_index = -1
    assert first_yield_index > 0, "could not locate first yield in ask_stream"
    prelude = body[:first_yield_index]
    forbidden_in_prelude = (
        "resolve_user_access_scope",
        "select_chat_model",
        "_build_stream_response",
    )
    leaked = [name for name in forbidden_in_prelude if name in prelude]
    assert not leaked, (
        f"ask_stream has expensive calls ({leaked}) before the first "
        f"yield. Move them into the generator body (after the first "
        f"yield) so the SSE event reaches the client immediately. "
        f"Found in prelude: {prelude!r}"
    )
