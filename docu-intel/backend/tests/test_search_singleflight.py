"""S3.3 — single-flight for repeated ``search_text`` / ``search_hybrid``.

The previous implementation ran the full retrieval pipeline once
per request, so a frontend that fired the same query N times in
quick succession (typing a refinement, opening two tabs, polling)
would pay the cost N times and produce N duplicate result sets.

The fix is a synchronous single-flight in
``services/search_singleflight.py`` that collapses identical
concurrent requests into a single shared call. This test pins
the contract: N concurrent threads requesting the same key
trigger exactly one ``work`` call and all callers see the same
result.
"""
from __future__ import annotations

import threading
from typing import Any

import pytest

from app.services.search_singleflight import (
    SearchSingleFlight,
    search_singleflight,
)


def test_single_flight_collapses_concurrent_identical_requests():
    """N concurrent threads requesting the same key must trigger
    exactly one ``work`` call and all callers must observe the
    same result.
    """
    flight = SearchSingleFlight()
    call_count = 0
    call_lock = threading.Lock()

    def work():
        nonlocal call_count
        with call_lock:
            call_count += 1
        # Tiny sleep so any follower that arrived late still
        # joins the same flight instead of starting a new one.
        import time

        time.sleep(0.01)
        return [{"r": 42, "payload": "hello"}]

    results: list[tuple[int, list[dict[str, Any]], bool]] = []
    errors: list[BaseException] = []
    barrier = threading.Barrier(8)

    def runner(thread_id: int) -> None:
        try:
            barrier.wait()  # all threads start the call at the same time
            value, waited = flight.run("k1", work)
            results.append((thread_id, value, waited))
        except BaseException as exc:  # pragma: no cover - test only
            errors.append(exc)

    threads = [threading.Thread(target=runner, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"unexpected errors: {errors}"
    assert call_count == 1, f"expected 1 work call, got {call_count}"
    assert len(results) == 8
    # All callers must see the same value.
    for _, value, _ in results:
        assert value == [{"r": 42, "payload": "hello"}]
    # Exactly one caller was the leader (waited=False), the rest waited.
    leaders = [r for r in results if not r[2]]
    followers = [r for r in results if r[2]]
    assert len(leaders) == 1, f"expected 1 leader, got {len(leaders)}"
    assert len(followers) == 7


def test_single_flight_different_keys_run_independently():
    """Two distinct keys must run independently: the second key
    triggers its own ``work`` call even if the first is still
    in flight.
    """
    flight = SearchSingleFlight()
    counts = {"k1": 0, "k2": 0}
    locks = {k: threading.Lock() for k in counts}

    def make_work(key: str):
        def work():
            with locks[key]:
                counts[key] += 1
            return [key]

        return work

    results: list[tuple[str, list[str]]] = []

    def runner(key: str) -> None:
        value, _ = flight.run(key, make_work(key))
        results.append((key, value))

    t1 = threading.Thread(target=runner, args=("k1",))
    t2 = threading.Thread(target=runner, args=("k2",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert counts == {"k1": 1, "k2": 1}
    assert ("k1", ["k1"]) in results
    assert ("k2", ["k2"]) in results


def test_make_key_is_stable_and_distinguishes_inputs():
    """``SearchSingleFlight.make_key`` must produce the same key
    for equal inputs and different keys for different inputs.
    """
    a = SearchSingleFlight.make_key("hola", 20, "scope-1")
    b = SearchSingleFlight.make_key("hola", 20, "scope-1")
    c = SearchSingleFlight.make_key("hola", 20, "scope-2")
    d = SearchSingleFlight.make_key("hola", 21, "scope-1")
    assert a == b
    assert a != c, "scope should affect the key"
    assert a != d, "limit should affect the key"


def test_module_level_singleton_is_usable():
    """The module exposes a process-wide singleton
    (``search_singleflight``) for callers that do not want to
    instantiate their own.
    """
    assert search_singleflight is not None
    value, waited = search_singleflight.run(
        SearchSingleFlight.make_key("singleton-probe"),
        lambda: [1, 2, 3],
    )
    assert value == [1, 2, 3]
    assert waited is False
