"""
Token bucket rate limiter per agent.

Limits: max N requests per second per agent.
Configuration via Settings (GUARDMCP_RATE_LIMIT_RPS, GUARDMCP_RATE_LIMIT_BURST).
"""

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class _Bucket:
    tokens: float
    last_refill: float = field(default_factory=time.monotonic)


class RateLimiter:
    """
    Token bucket limiter. Thread-safe via asyncio.Lock per agent.

    rps: sustained requests per second allowed per agent
    burst: max tokens (allows short bursts above rps)
    """

    def __init__(self, rps: float = 0.0, burst: int = 0) -> None:
        self._rps = rps
        self._burst = burst
        self._buckets: dict[str, _Bucket] = defaultdict(lambda: _Bucket(tokens=float(burst)))
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    @property
    def enabled(self) -> bool:
        return self._rps > 0

    async def check(self, agent: str) -> bool:
        """
        Return True if request is allowed, False if rate-limited.
        No-op (always True) when rps == 0 (disabled).
        """
        if not self.enabled:
            return True

        async with self._locks[agent]:
            bucket = self._buckets[agent]
            now = time.monotonic()
            elapsed = now - bucket.last_refill
            bucket.tokens = min(
                self._burst,
                bucket.tokens + elapsed * self._rps,
            )
            bucket.last_refill = now
            allowed = bucket.tokens >= 1
            if allowed:
                bucket.tokens -= 1
            # M3: opportunistically evict idle full buckets so the maps don't
            # grow unbounded across many distinct agents over a long uptime.
            self._maybe_evict(now)
            return allowed

    def _maybe_evict(self, now: float, idle_seconds: float = 3600.0) -> None:
        # Only sweep occasionally and only when the map is non-trivial.
        if len(self._buckets) < 1024:
            return
        stale = [
            a
            for a, b in self._buckets.items()
            if now - b.last_refill > idle_seconds and b.tokens >= self._burst
        ]
        for a in stale:
            self._buckets.pop(a, None)
            self._locks.pop(a, None)
