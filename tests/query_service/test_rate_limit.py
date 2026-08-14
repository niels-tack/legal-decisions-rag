"""Unit tests for ``src.query_service.rate_limit``.

Exercises ``TokenBucketRateLimiter`` directly (with a controllable clock) so
the refill/consume arithmetic can be verified without needing real wall
-clock time to pass, plus a direct check of the ``rate_limit`` FastAPI
dependency's rejection behavior.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from src.query_service.rate_limit import TokenBucketRateLimiter, rate_limit


def test_allows_requests_up_to_capacity() -> None:
    """A fresh bucket allows exactly `capacity` requests before rejecting."""
    limiter = TokenBucketRateLimiter(capacity=3, refill_period_seconds=60.0)

    results = [limiter.allow("1.2.3.4") for _ in range(4)]

    assert results == [True, True, True, False]


def test_different_keys_have_independent_buckets() -> None:
    """One key being exhausted must not affect another key's budget."""
    limiter = TokenBucketRateLimiter(capacity=1, refill_period_seconds=60.0)

    assert limiter.allow("1.2.3.4") is True
    assert limiter.allow("1.2.3.4") is False
    assert limiter.allow("5.6.7.8") is True


def test_tokens_refill_over_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """After enough simulated time passes, a spent bucket allows again."""
    limiter = TokenBucketRateLimiter(capacity=2, refill_period_seconds=60.0)
    clock = [1000.0]
    monkeypatch.setattr(
        "src.query_service.rate_limit.time.monotonic", lambda: clock[0]
    )

    assert limiter.allow("1.2.3.4") is True
    assert limiter.allow("1.2.3.4") is True
    assert limiter.allow("1.2.3.4") is False

    clock[0] += 30.0  # half the refill period -> one token back
    assert limiter.allow("1.2.3.4") is True
    assert limiter.allow("1.2.3.4") is False


class _FakeClient:
    """Stand-in for FastAPI's ``Request.client``."""

    def __init__(self, host: str) -> None:
        self.host = host


class _FakeRequest:
    """Minimal stand-in for a FastAPI ``Request`` the dependency reads from."""

    def __init__(self, host: str | None) -> None:
        self.client = _FakeClient(host) if host is not None else None
        self.url = type("_Url", (), {"path": "/search"})()


def test_rate_limit_dependency_raises_429_when_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The FastAPI dependency raises a 429 once the shared limiter is exhausted."""
    import src.query_service.rate_limit as rate_limit_module

    monkeypatch.setattr(
        rate_limit_module, "_limiter", TokenBucketRateLimiter(capacity=1)
    )
    request = _FakeRequest("9.9.9.9")

    # first call consumes the only token, must not raise
    rate_limit(request)  # ty: ignore[invalid-argument-type]

    with pytest.raises(HTTPException) as exc_info:
        rate_limit(request)  # ty: ignore[invalid-argument-type]

    assert exc_info.value.status_code == 429


def test_rate_limit_dependency_handles_missing_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A request with no ``client`` (e.g. some test transports) doesn't crash."""
    import src.query_service.rate_limit as rate_limit_module

    monkeypatch.setattr(
        rate_limit_module, "_limiter", TokenBucketRateLimiter(capacity=1)
    )

    rate_limit(_FakeRequest(None))  # ty: ignore[invalid-argument-type]
