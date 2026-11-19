"""Rate limiting with a token bucket in Redis, shared by both order-service copies.

A limit inside nginx or inside 1 container would count each copy separately; the Redis
bucket gives 1 limit per client across all copies. Redis's own clock (TIME) is used, so
copies with slightly different clocks still agree.
"""

import logging
import math
from dataclasses import dataclass
from importlib import resources

import redis

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Decision:
    allowed: bool
    retry_after_seconds: int = 0


class RateLimiter:
    def __init__(self, client: redis.Redis, capacity: int, per_second: float) -> None:
        source = resources.files("order_service").joinpath("lua", "token_bucket.lua")
        self._script = client.register_script(source.read_text(encoding="utf-8"))
        self._capacity = capacity
        self._per_second = per_second

    def check(self, client_id: str) -> Decision:
        try:
            allowed, retry_ms = self._script(
                keys=[f"ratelimit:{client_id}"], args=[self._capacity, self._per_second]
            )
        except redis.RedisError:
            # Fail open: a broken limiter must not take the order API down with it.
            log.warning("rate limiter unavailable; allowing the request", exc_info=True)
            return Decision(True)
        if allowed:
            return Decision(True)
        return Decision(False, max(1, math.ceil(int(retry_ms) / 1000)))


def client_id(headers: dict[str, str], peer: str | None) -> str:
    """X-Client-Id if given, else the first X-Forwarded-For address (set by nginx), else
    the address of the direct caller."""
    given = headers.get("x-client-id", "").strip()
    if given:
        return f"id:{given[:64]}"
    forwarded = headers.get("x-forwarded-for", "").split(",")[0].strip()
    return f"ip:{forwarded or peer or 'unknown'}"
