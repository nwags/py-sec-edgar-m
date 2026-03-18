from __future__ import annotations

from py_sec_edgar.rate_limit import RequestRateLimiter


def test_rate_limiter_throttles_repeated_requests():
    state = {"t": 0.0}
    sleeps = []

    def now_func():
        return state["t"]

    def sleep_func(seconds: float):
        sleeps.append(seconds)
        state["t"] += seconds

    limiter = RequestRateLimiter(2.0, now_func=now_func, sleep_func=sleep_func)

    assert limiter.wait() == 0.0
    assert limiter.wait() == 0.5
    assert limiter.wait() == 0.5
    assert sleeps == [0.5, 0.5]


def test_rate_limiter_disabled_when_non_positive_rate():
    state = {"t": 0.0}
    sleeps = []

    def now_func():
        return state["t"]

    def sleep_func(seconds: float):
        sleeps.append(seconds)
        state["t"] += seconds

    limiter = RequestRateLimiter(0.0, now_func=now_func, sleep_func=sleep_func)

    assert limiter.wait() == 0.0
    assert limiter.wait() == 0.0
    assert sleeps == []
