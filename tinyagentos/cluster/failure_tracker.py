"""Circuit breaker for cluster worker routing.

Tracks per-worker failure counts within a sliding time window so the
TaskRouter can skip workers that have repeatedly failed, instead of
serially trying all N workers and blocking for ``timeout * N`` seconds
before giving up (taOS #640, Fix 3).

State is in-memory only (no SQLite): the circuit breaker resets on
controller restart, which is the safe default — a freshly-started
controller has no failure history and should give every worker a
clean chance.
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import NamedTuple


class _FailureRecord(NamedTuple):
    failures: int
    first_failure_at: float


# Sensible defaults: 5 failures in 60 seconds trips the breaker.
# A tripped worker is excluded from routing for the cooldown period.
DEFAULT_FAILURE_THRESHOLD = 3
DEFAULT_WINDOW_SECONDS = 60.0


class FailureTracker:
    """Per-worker failure counter with a sliding time window.

    After ``failure_threshold`` failures within ``window_seconds``,
    ``is_tripped(worker_name)`` returns ``True`` and the router skips
    that worker.  The window resets once enough time has passed since
    the first failure in the current window.
    """

    def __init__(
        self,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
    ):
        self._failure_threshold = failure_threshold
        self._window_seconds = window_seconds
        self._records: dict[str, _FailureRecord] = defaultdict(
            lambda: _FailureRecord(0, 0.0)
        )

    def record_failure(self, worker_name: str) -> None:
        """Register a failure for the given worker.

        After the window has elapsed since the first failure, the counter
        resets automatically on the next failure.
        """
        now = time.time()
        rec = self._records[worker_name]
        if rec.first_failure_at > 0 and (now - rec.first_failure_at) > self._window_seconds:
            # Window expired — reset
            self._records[worker_name] = _FailureRecord(1, now)
        elif rec.first_failure_at == 0:
            self._records[worker_name] = _FailureRecord(1, now)
        else:
            self._records[worker_name] = _FailureRecord(
                rec.failures + 1, rec.first_failure_at
            )

    def record_success(self, worker_name: str) -> None:
        """Clear the failure record for a worker after a successful request."""
        self._records.pop(worker_name, None)

    def is_tripped(self, worker_name: str) -> bool:
        """Return True if the worker's circuit breaker is currently open.

        The breaker opens when ``failure_threshold`` failures have occurred
        within ``window_seconds`` and not enough time has elapsed since the
        first failure to reset the window.
        """
        rec = self._records.get(worker_name)
        if rec is None:
            return False
        now = time.time()
        if rec.first_failure_at > 0 and (now - rec.first_failure_at) > self._window_seconds:
            # Window expired — auto-reset
            self._records.pop(worker_name, None)
            return False
        return rec.failures >= self._failure_threshold

    def reset(self, worker_name: str) -> None:
        """Manually reset the circuit breaker for a worker."""
        self._records.pop(worker_name, None)

    def reset_all(self) -> None:
        """Reset all circuit breakers."""
        self._records.clear()
