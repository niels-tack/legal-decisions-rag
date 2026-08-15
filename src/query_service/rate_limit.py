"""Per-IP rate limiting for the keyless public query API.

Per the technical requirements, the query service has no end-user
authentication of any kind - end users never hold a key, and neither does
any client integration (that model, and the client integrations that relied
on it, moved to ``v2/``). Abuse protection instead comes from per-IP rate
limiting (this module), origin-locked CORS (configured directly on the
FastAPI app in ``main.py``), and response-size caps
(``src.query_service.search._MAX_EXCERPT_CHARS``).

An in-process token bucket is sufficient at this project's expected scale
(low, bursty, ad hoc traffic) - no shared/external store is needed.
"""

from __future__ import annotations

import logging
import os
import time

from fastapi import HTTPException, Request, status

logger = logging.getLogger(__name__)

RATE_LIMIT_PER_MINUTE_ENV_VAR = "RATE_LIMIT_PER_MINUTE"
DEFAULT_RATE_LIMIT_PER_MINUTE = 30


class TokenBucketRateLimiter:
    """A simple per-key token bucket, refilled continuously over time."""

    def __init__(self, capacity: int, refill_period_seconds: float = 60.0) -> None:
        """Configure the bucket's capacity and refill rate.

        Args:
            capacity: Maximum tokens (= requests) a single key can burst to,
                and the number that refill every ``refill_period_seconds``.
            refill_period_seconds: Time window the ``capacity`` refills
                over. Defaults to one minute, matching how the rate limit
                is configured (requests per minute).
        """
        self._capacity = capacity
        self._refill_per_second = capacity / refill_period_seconds
        self._buckets: dict[str, tuple[float, float]] = {}

    def allow(self, key: str) -> bool:
        """Check whether ``key`` has a token available, consuming one if so.

        Args:
            key: Identifies the caller to rate-limit, e.g. a client IP.

        Returns:
            True if a token was available and has now been consumed, False
            if ``key`` is currently out of tokens.
        """
        now = time.monotonic()
        tokens, last_refill = self._buckets.get(key, (float(self._capacity), now))
        tokens = min(self._capacity, tokens + (now - last_refill) * self._refill_per_second)

        if tokens < 1.0:
            self._buckets[key] = (tokens, now)
            return False

        self._buckets[key] = (tokens - 1.0, now)
        return True


# Module-level singleton: request volume at this project's expected scale
# never justifies a shared/external rate-limit store, and a dependency
# needs a stable instance to track state across requests within one
# running container.
_limiter = TokenBucketRateLimiter(
    capacity=int(
        os.environ.get(RATE_LIMIT_PER_MINUTE_ENV_VAR, DEFAULT_RATE_LIMIT_PER_MINUTE)
    )
)


def rate_limit(request: Request) -> None:
    """FastAPI dependency: reject a request if its client IP is over budget.

    Args:
        request: The current request, used to read the client's IP.

    Raises:
        HTTPException: With status 429 if the client has no tokens left.
            The rejection is logged (client IP + path) so container logs
            can surface abuse or a misbehaving client, per the technical
            requirements' rejection-logging requirement.
    """
    client_ip = request.client.host if request.client else "unknown"
    if not _limiter.allow(client_ip):
        logger.warning("Rate limit exceeded for %s on %s", client_ip, request.url.path)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please slow down and try again shortly.",
        )
