"""Rate limiting — integration + concurrency/perf coverage.

Previously only unit-tested in isolation (test_rate_limiter.py) with a
hand-constructed result dict proving the envelope SHAPE (test_error_contract.py
/ test_observability_and_codes.py). Nothing drove a REAL GuardPipeline.run()
with a REAL RateLimiter attached end to end, and nothing exercised the
token-bucket under actual concurrent access (the one place a race condition
could double-spend tokens) or the idle-bucket eviction path.
"""

from __future__ import annotations

import asyncio

import pytest

from guardmcp.core.approval.store import ApprovalStore
from guardmcp.core.audit.logger import AuditLogger
from guardmcp.core.models.domain import Action
from guardmcp.core.pipeline import GuardPipeline
from guardmcp.core.policy.engine import PolicyEngine
from guardmcp.core.policy.models import CollectionPolicy, Policy
from guardmcp.core.ratelimit.limiter import RateLimiter
from guardmcp.core.risk.engine import RiskEngine

# ── Integration: real GuardPipeline.run() + real RateLimiter ────────────────


class _Loader:
    def __init__(self, policy):
        self._p = policy

    def get(self, agent):
        return self._p


def _pipeline(tmp_path, limiter):
    policy = Policy(agent="claude", mode="readonly", collections=CollectionPolicy(allow=["*"]))
    return GuardPipeline(
        policy_loader=_Loader(policy),
        policy_engine=PolicyEngine(),
        risk_engine=RiskEngine(),
        audit_logger=AuditLogger(tmp_path / "audit.jsonl"),
        approval_store=ApprovalStore(timeout_seconds=1.0),
        executor=None,
        limiter=limiter,
    )


@pytest.mark.asyncio
async def test_pipeline_run_allows_within_burst(tmp_path):
    limiter = RateLimiter(rps=1000, burst=2)
    pipeline = _pipeline(tmp_path, limiter)
    out = await pipeline.run("claude", "users", Action.FIND, {"filter": {}})
    # policy has no executor -> would error downstream, but NOT rate-limited.
    assert out.get("code") != "RATE_LIMITED"


@pytest.mark.asyncio
async def test_pipeline_run_returns_rate_limited_error_when_exhausted(tmp_path):
    limiter = RateLimiter(rps=0.001, burst=1)  # effectively no refill in-test
    pipeline = _pipeline(tmp_path, limiter)
    first = await pipeline.run("claude", "users", Action.FIND, {"filter": {}})
    assert first.get("code") != "RATE_LIMITED"  # consumes the one token

    second = await pipeline.run("claude", "users", Action.FIND, {"filter": {}})
    assert second == {
        "status": "error",
        "reason": "rate limit exceeded for agent 'claude'. Try again shortly.",
        "code": "RATE_LIMITED",
    }


@pytest.mark.asyncio
async def test_rate_limited_request_never_reaches_policy_evaluation(tmp_path):
    """A rate-limited request must short-circuit BEFORE evaluate() runs — no
    audit event, no policy check, for the request that got throttled."""
    limiter = RateLimiter(rps=0.001, burst=1)
    pipeline = _pipeline(tmp_path, limiter)
    await pipeline.run("claude", "users", Action.FIND, {"filter": {}})  # consumes token

    calls: list[str] = []
    original_evaluate = pipeline.evaluate

    def _spy(*args, **kwargs):
        calls.append("evaluate")
        return original_evaluate(*args, **kwargs)

    pipeline.evaluate = _spy
    await pipeline.run("claude", "users", Action.FIND, {"filter": {}})
    assert calls == []  # evaluate() never called for the throttled request


@pytest.mark.asyncio
async def test_per_agent_isolation_through_real_pipeline(tmp_path):
    limiter = RateLimiter(rps=0.001, burst=1)
    pipeline = _pipeline(tmp_path, limiter)
    claude_first = await pipeline.run("claude", "users", Action.FIND, {"filter": {}})
    other = await pipeline.run("other-agent", "users", Action.FIND, {"filter": {}})
    assert claude_first.get("code") != "RATE_LIMITED"
    assert other.get("code") != "RATE_LIMITED"  # independent bucket, not shared


# ── Concurrency: token bucket must not double-spend under real concurrency ──


@pytest.mark.asyncio
async def test_concurrent_checks_never_allow_more_than_burst():
    """Fire N concurrent check() calls for one agent — the asyncio.Lock per
    agent must serialize them so at most `burst` succeed, never more (a race
    in the read-modify-write of bucket.tokens would over-allow)."""
    limiter = RateLimiter(rps=0.001, burst=5)
    results = await asyncio.gather(*(limiter.check("agent") for _ in range(50)))
    assert sum(results) == 5


@pytest.mark.asyncio
async def test_concurrent_checks_across_many_agents_stay_isolated():
    """Load-shaped: many agents, many concurrent requests each — no agent's
    bucket leaks into another's under concurrent access."""
    limiter = RateLimiter(rps=0.001, burst=3)
    agents = [f"agent-{i}" for i in range(20)]

    async def _burst_for(agent):
        results = await asyncio.gather(*(limiter.check(agent) for _ in range(10)))
        return agent, sum(results)

    outcomes = await asyncio.gather(*(_burst_for(a) for a in agents))
    for _agent, allowed_count in outcomes:
        assert allowed_count == 3  # exactly `burst`, regardless of the other 19 agents


# ── Eviction: idle full buckets get swept once the map grows large ─────────


@pytest.mark.asyncio
async def test_idle_full_buckets_evicted_past_threshold():
    limiter = RateLimiter(rps=10, burst=5)
    # Populate past the 1024 eviction threshold with full (never-touched) buckets.
    for i in range(1030):
        limiter._buckets[f"idle-{i}"] = limiter._buckets[f"idle-{i}"]  # materialize default
        limiter._buckets[f"idle-{i}"].last_refill -= 7200  # 2h idle, past the 1h threshold

    before = len(limiter._buckets)
    await limiter.check("trigger-agent")  # any check() opportunistically sweeps
    after = len(limiter._buckets)

    assert before >= 1024
    assert after < before  # idle full buckets were purged
