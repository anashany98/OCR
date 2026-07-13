"""In-process single-flight coordination for isolated chat cache keys."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass


@dataclass
class _Flight:
    lock: asyncio.Lock
    users: int = 0


@dataclass
class FlightLease:
    key: str
    waited: bool
    _flight: _Flight
    _owner: "ChatSingleFlight"
    _released: bool = False

    async def release(self) -> None:
        if self._released:
            return
        self._released = True
        self._flight.lock.release()
        async with self._owner._guard:
            self._flight.users -= 1
            if self._flight.users == 0 and not self._flight.lock.locked():
                self._owner._flights.pop(self.key, None)


class ChatSingleFlight:
    """Serialize identical cold cache keys inside one backend process.

    Keys are already SHA-256 cache keys containing user, permissions, session,
    model, prompt and knowledge versions. Nothing less isolated is accepted.
    """

    def __init__(self) -> None:
        self._guard = asyncio.Lock()
        self._flights: dict[str, _Flight] = {}

    async def acquire(self, key: str) -> FlightLease:
        async with self._guard:
            flight = self._flights.get(key)
            waited = flight is not None and flight.lock.locked()
            if flight is None:
                flight = _Flight(lock=asyncio.Lock())
                self._flights[key] = flight
            flight.users += 1
        try:
            await flight.lock.acquire()
        except BaseException:
            async with self._guard:
                flight.users -= 1
                if flight.users == 0 and not flight.lock.locked():
                    self._flights.pop(key, None)
            raise
        return FlightLease(key=key, waited=waited, _flight=flight, _owner=self)


chat_singleflight = ChatSingleFlight()
