"""In-process single-flight coordination for repeated search queries.

When the frontend fires the same query several times in quick
succession (typing a refinement, opening two tabs, polling),
``search_text`` / ``search_hybrid`` / ``search_semantic`` would
otherwise run the full retrieval pipeline N times and produce N
duplicate result sets. The single-flight collapses those identical
cold requests into a single shared call: the first request runs,
the other N-1 wait on the same in-memory future, and every caller
sees the same ``list[SearchResult]``.

The pattern mirrors the async ``ChatSingleFlight`` in
``ai_singleflight.py`` but stays synchronous because
``search_service`` is called from sync FastAPI handlers. The
key is built from the inputs that actually change the result
set (question + limit + scope + filters) so two users searching
for the same word do *not* share a flight.
"""
from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass
from typing import Any, Callable, TypeVar

T = TypeVar("T")


@dataclass
class _SyncFlight:
    event: threading.Event
    users: int
    value: list[Any] | None
    error: BaseException | None


class SearchSingleFlight:
    """Synchronous single-flight for the public search service.

    The implementation is intentionally simple: a ``threading.Lock``
    guards a ``dict`` of in-flight queries. The first thread to
    request a key runs the work; the others wait on a
    ``threading.Event`` and then read the shared value. The
    in-flight record is removed when the last user releases it so
    the dict does not grow unbounded.
    """

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._flights: dict[str, _SyncFlight] = {}

    @staticmethod
    def make_key(*parts: Any) -> str:
        """Build a stable, opaque key from the inputs that affect
        the result. Two callers with the same key see the same
        value; two callers with different inputs do not share.
        """
        blob = "|".join(repr(part) for part in parts).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()

    def run(
        self, key: str, work: Callable[[], list[T]]
    ) -> tuple[list[T], bool]:
        """Execute ``work`` under the single-flight contract.

        Returns ``(value, waited)`` where ``waited`` is True if the
        caller piggy-backed on an in-flight execution rather than
        being the one that ran the work.
        """
        with self._guard:
            flight = self._flights.get(key)
            waited = flight is not None
            if flight is None:
                flight = _SyncFlight(
                    event=threading.Event(),
                    users=1,
                    value=None,
                    error=None,
                )
                self._flights[key] = flight
            else:
                flight.users += 1
        if not waited:
            # We are the leader: run the work and broadcast.
            try:
                value = work()
            except BaseException as exc:  # propagate to followers
                with self._guard:
                    flight.error = exc
                    flight.event.set()
                self._cleanup(key, flight)
                raise
            else:
                with self._guard:
                    flight.value = list(value)
                    flight.event.set()
                self._cleanup(key, flight)
                return flight.value, False
        # Follower: wait for the leader and read the shared value.
        flight.event.wait()
        if flight.error is not None:
            raise flight.error
        return list(flight.value or []), True

    def _cleanup(self, key: str, flight: _SyncFlight) -> None:
        with self._guard:
            flight.users -= 1
            if flight.users == 0:
                # Only remove if this is still the record we
                # registered (defensive against any future refactor
                # that swaps the entry).
                if self._flights.get(key) is flight:
                    self._flights.pop(key, None)


search_singleflight = SearchSingleFlight()
