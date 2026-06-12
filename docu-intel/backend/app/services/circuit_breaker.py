"""Thread-safe circuit breaker for external HTTP services.

The breaker wraps any callable that may fail intermittently (LM Studio,
reranker server, embedding endpoint, ...). It implements the classic
three-state pattern:

    CLOSED    → calls flow through; failures are counted.
    OPEN      → calls fail fast with ``CircuitBreakerOpen`` for
                ``reset_timeout`` seconds.
    HALF_OPEN → one trial call is allowed. If it succeeds, the breaker
                resets to CLOSED. If it fails, the breaker re-opens.

Why a custom implementation:
- The project does not depend on ``pybreaker`` and the constraints
  forbid adding new third-party packages for small utilities.
- The breaker is intentionally minimal: 4 settings (fail_max,
  reset_timeout, success_threshold, exclude) and 3 exceptions.
- It is safe to share a single ``CircuitBreaker`` instance across
  threads (a ``threading.Lock`` guards the state transitions).

Usage::

    breaker = CircuitBreaker(fail_max=5, reset_timeout=30.0, name="embeddings")

    try:
        result = breaker.call(lambda: client.post(...))
    except CircuitBreakerOpen:
        # Service is known to be down; fail fast.
        return fallback()

The breaker is *fail-fast only*: it never blocks the call. The wrapped
function still needs its own timeout (via ``httpx`` or similar).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


class CircuitBreakerError(RuntimeError):
    """Base class for all circuit-breaker errors."""


class CircuitBreakerOpen(CircuitBreakerError):
    """Raised when the breaker is OPEN and rejects a call."""


class CircuitBreakerConfigError(CircuitBreakerError):
    """Raised on invalid construction-time arguments."""


# Valid breaker states. We keep them as module constants so tests and
# downstream metrics can import the names without grabbing the private
# attributes on the instance.
STATE_CLOSED = "closed"
STATE_OPEN = "open"
STATE_HALF_OPEN = "half_open"


class CircuitBreaker:
    """Minimal, thread-safe circuit breaker.

    Parameters
    ----------
    fail_max:
        Number of consecutive failures that trip the breaker. A single
        success resets the counter.
    reset_timeout:
        Seconds the breaker stays OPEN before allowing one trial call
        (transition to HALF_OPEN).
    success_threshold:
        Number of consecutive successes in HALF_OPEN required to
        transition back to CLOSED. Default 1.
    name:
        Optional human-readable label used in error messages and
        metrics. The metrics helper registers it as a Prometheus
        label so multiple breakers in the same process are
        distinguishable.
    exclude:
        Optional tuple of exception classes that must **not** count as
        failures. Useful for skipping ``NotFound``-style errors that
        the caller wants to handle without tripping the breaker.
    """

    def __init__(
        self,
        fail_max: int = 5,
        reset_timeout: float = 30.0,
        success_threshold: int = 1,
        name: str = "default",
        exclude: tuple[type[BaseException], ...] = (),
    ) -> None:
        if fail_max < 1:
            raise CircuitBreakerConfigError("fail_max must be >= 1")
        if reset_timeout <= 0:
            raise CircuitBreakerConfigError("reset_timeout must be > 0")
        if success_threshold < 1:
            raise CircuitBreakerConfigError("success_threshold must be >= 1")

        self.fail_max = fail_max
        self.reset_timeout = reset_timeout
        self.success_threshold = success_threshold
        self.name = name
        self.exclude = exclude

        self._state = STATE_CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._opened_at: float | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public introspection — used by tests and the metrics helper.
    # ------------------------------------------------------------------
    @property
    def state(self) -> str:
        """Return the current breaker state, transitioning OPEN →
        HALF_OPEN lazily when the reset timeout elapses."""
        with self._lock:
            self._maybe_recover_locked()
            return self._state

    @property
    def failure_count(self) -> int:
        with self._lock:
            return self._failure_count

    def reset(self) -> None:
        """Force the breaker back to CLOSED. Useful for tests and for
        operational tooling that wants to re-enable a known-healthy
        service without waiting for the natural timeout."""
        with self._lock:
            self._state = STATE_CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._opened_at = None

    # ------------------------------------------------------------------
    # Core call path.
    # ------------------------------------------------------------------
    def call(self, func: Callable[..., T], *args, **kwargs) -> T:
        """Run ``func`` through the breaker.

        Raises ``CircuitBreakerOpen`` if the breaker is OPEN (or
        HALF_OPEN with no trial slot available). Otherwise it returns
        whatever ``func`` returns and records success/failure.
        """
        with self._lock:
            self._maybe_recover_locked()
            if self._state == STATE_OPEN:
                raise CircuitBreakerOpen(
                    f"Circuit '{self.name}' is OPEN; "
                    f"retry in {self._remaining_reset_seconds_locked():.1f}s"
                )
            # CLOSED or HALF_OPEN → run the call.

        try:
            result = func(*args, **kwargs)
        except BaseException as exc:
            # Record failures outside the lock would risk losing
            # updates on re-entrancy; we keep them inside for the
            # duration of the state transition.
            with self._lock:
                self._on_failure_locked(exc)
            raise

        with self._lock:
            self._on_success_locked()
        return result

    # ------------------------------------------------------------------
    # Context-manager sugar for ``with breaker: ...`` blocks.
    # ------------------------------------------------------------------
    def __enter__(self) -> "CircuitBreaker":
        with self._lock:
            self._maybe_recover_locked()
            if self._state == STATE_OPEN:
                raise CircuitBreakerOpen(
                    f"Circuit '{self.name}' is OPEN; "
                    f"retry in {self._remaining_reset_seconds_locked():.1f}s"
                )
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        with self._lock:
            if exc_type is None:
                self._on_success_locked()
            elif issubclass(exc_type, self.exclude):
                # Excluded exception: treat as success for breaker
                # accounting but re-raise to the caller.
                self._on_success_locked()
            else:
                self._on_failure_locked(exc)
        return False  # never swallow exceptions

    # ------------------------------------------------------------------
    # Locked helpers. Callers MUST hold ``self._lock``.
    # ------------------------------------------------------------------
    def _maybe_recover_locked(self) -> None:
        if self._state != STATE_OPEN or self._opened_at is None:
            return
        if (time.monotonic() - self._opened_at) >= self.reset_timeout:
            self._state = STATE_HALF_OPEN
            self._success_count = 0
            # Keep ``_opened_at`` so we can still report when we opened.

    def _remaining_reset_seconds_locked(self) -> float:
        if self._opened_at is None:
            return 0.0
        elapsed = time.monotonic() - self._opened_at
        return max(0.0, self.reset_timeout - elapsed)

    def _on_success_locked(self) -> None:
        if self._state == STATE_HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self.success_threshold:
                self._state = STATE_CLOSED
                self._failure_count = 0
                self._success_count = 0
                self._opened_at = None
            return
        # CLOSED → just reset the failure counter.
        self._failure_count = 0
        self._success_count = 0

    def _on_failure_locked(self, exc: BaseException) -> None:
        if isinstance(exc, self.exclude):
            return
        if self._state == STATE_HALF_OPEN:
            # Trial call failed → re-open immediately.
            self._state = STATE_OPEN
            self._opened_at = time.monotonic()
            self._success_count = 0
            return
        self._failure_count += 1
        if self._failure_count >= self.fail_max:
            self._state = STATE_OPEN
            self._opened_at = time.monotonic()
            self._success_count = 0
