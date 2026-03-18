from __future__ import annotations

import threading
import time


class RequestRateLimiter:
    """Simple single-process request rate limiter.

    This limiter enforces a minimum spacing between outbound requests.
    """

    def __init__(self, max_requests_per_second: float, now_func=None, sleep_func=None):
        self.max_requests_per_second = float(max_requests_per_second)
        self._now = now_func or time.monotonic
        self._sleep = sleep_func or time.sleep
        self._lock = threading.Lock()
        self._next_allowed_at: float | None = None

    @property
    def enabled(self) -> bool:
        return self.max_requests_per_second > 0

    @property
    def interval_seconds(self) -> float:
        if not self.enabled:
            return 0.0
        return 1.0 / self.max_requests_per_second

    def wait(self) -> float:
        """Wait until the next request is allowed and return sleep duration."""
        if not self.enabled:
            return 0.0

        slept = 0.0
        interval = self.interval_seconds
        with self._lock:
            now = self._now()
            if self._next_allowed_at is None:
                self._next_allowed_at = now + interval
                return 0.0

            delay = self._next_allowed_at - now
            if delay > 0:
                self._sleep(delay)
                slept = delay
                now = self._now()

            self._next_allowed_at = max(now, self._next_allowed_at) + interval
            return slept


_shared_limiter: RequestRateLimiter | None = None
_shared_limiter_rps: float | None = None
_shared_limiter_lock = threading.Lock()


def get_shared_rate_limiter(max_requests_per_second: float) -> RequestRateLimiter:
    """Return a process-wide limiter instance configured for the current rate."""
    global _shared_limiter, _shared_limiter_rps

    rps = float(max_requests_per_second)
    with _shared_limiter_lock:
        if _shared_limiter is None or _shared_limiter_rps != rps:
            _shared_limiter = RequestRateLimiter(rps)
            _shared_limiter_rps = rps
        return _shared_limiter

