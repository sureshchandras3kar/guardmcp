"""Tests for the per-agent token-bucket rate limiter."""

import asyncio

from guardmcp.core.ratelimit.limiter import RateLimiter


async def test_disabled_when_rps_zero():
    limiter = RateLimiter(rps=0)
    for _ in range(100):
        assert await limiter.check("agent") is True


async def test_burst_exhaustion():
    # High rps so refill during the test window is negligible; burst caps to 2.
    limiter = RateLimiter(rps=1000, burst=2)
    assert await limiter.check("agent") is True
    assert await limiter.check("agent") is True
    # Third immediate call: burst exhausted, refill in microseconds < 1 token.
    assert await limiter.check("agent") is False


async def test_refill_over_time():
    # rps=100, burst=1: consume the one token, then sleep to refill.
    limiter = RateLimiter(rps=100, burst=1)
    assert await limiter.check("agent") is True
    assert await limiter.check("agent") is False
    await asyncio.sleep(0.05)  # ~5 tokens refilled, capped at burst=1
    assert await limiter.check("agent") is True


async def test_per_agent_isolation():
    limiter = RateLimiter(rps=1000, burst=1)
    # Agent A exhausts its bucket.
    assert await limiter.check("A") is True
    assert await limiter.check("A") is False
    # Agent B has its own independent bucket.
    assert await limiter.check("B") is True
