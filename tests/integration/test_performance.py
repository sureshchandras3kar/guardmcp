"""Performance / load sanity checks — previously zero perf suite existed
(FEATURE_STATUS.md flagged this explicitly). These are generous-bound smoke
tests against catastrophic regressions (a change that makes the pipeline
10-100x slower, or breaks the audit chain under concurrency), NOT strict
latency SLAs — the numbers here are deliberately loose for CI stability
across different machines.

Uses mongomock-motor (no real MongoDB needed) so this runs in the same fast
unit-test-like environment as everything else, unlike tests/integration/
test_live_backends.py which needs testcontainers/Docker.
"""

from __future__ import annotations

import asyncio
import time

import pytest
from mongomock_motor import AsyncMongoMockClient

from guardmcp.core.approval.store import ApprovalStore
from guardmcp.core.audit.logger import AuditLogger
from guardmcp.core.audit.verify import verify_chain
from guardmcp.core.models.domain import Action
from guardmcp.core.pipeline import GuardPipeline
from guardmcp.core.policy.engine import PolicyEngine
from guardmcp.core.policy.models import CollectionPolicy, Policy
from guardmcp.core.risk.engine import RiskEngine
from guardmcp.plugins.mongodb.executor import MongoExecutor

pytestmark = pytest.mark.perf


class _Loader:
    def __init__(self, policy):
        self._p = policy

    def get(self, agent):
        return self._p


def _make_client():
    real = AsyncMongoMockClient()

    class _Client:
        def get_collection(self, name, database=None):
            return real["testdb"][name]

        def get_db(self, database=None):
            return real["testdb"]

        async def list_collection_names(self, database=None):
            return await real["testdb"].list_collection_names()

        async def list_databases(self):  # noqa: RUF029
            return [{"name": "testdb", "sizeOnDisk": 0}]

        def close(self):
            pass

    return _Client(), real


def _pipeline(tmp_path, hmac_secret="perf-test-secret"):
    policy = Policy(agent="claude", mode="readonly", collections=CollectionPolicy(allow=["*"]))
    client, real = _make_client()
    audit_path = tmp_path / "audit.jsonl"
    return (
        GuardPipeline(
            policy_loader=_Loader(policy),
            policy_engine=PolicyEngine(),
            risk_engine=RiskEngine(),
            audit_logger=AuditLogger(audit_path, hmac_secret=hmac_secret),
            approval_store=ApprovalStore(timeout_seconds=1.0),
            executor=MongoExecutor(client),
        ),
        real,
        audit_path,
    )


# ── Throughput: sequential + concurrent pipeline.run() ──────────────────────


@pytest.mark.asyncio
async def test_sequential_find_throughput(tmp_path):
    pipeline, real, _ = _pipeline(tmp_path)
    await real["testdb"]["users"].insert_many([{"i": i} for i in range(50)])

    n = 200
    start = time.monotonic()
    for _ in range(n):
        out = await pipeline.run("claude", "users", Action.FIND, {"filter": {}})
        assert out["status"] == "success"
    elapsed = time.monotonic() - start

    # Generous bound: 200 full evaluate->execute->mask->audit round trips
    # against an in-memory mock backend should not take anywhere near 10s.
    # This guards against an accidental O(n^2) regression, not a tight SLA.
    assert elapsed < 10.0, f"{n} sequential find() calls took {elapsed:.2f}s"


@pytest.mark.asyncio
async def test_concurrent_pipeline_run_all_succeed_and_audit_chain_stays_valid(tmp_path):
    """The audit HMAC chain is order-sensitive and single-writer (group-commit,
    per core/audit/logger.py) — this is the one place concurrency could
    corrupt correctness, not just throughput. Fire concurrent requests and
    verify EVERY one succeeded AND the resulting chain still verifies."""
    pipeline, real, audit_path = _pipeline(tmp_path)
    await real["testdb"]["users"].insert_many([{"i": i} for i in range(10)])

    n = 100
    start = time.monotonic()
    results = await asyncio.gather(
        *(pipeline.run("claude", "users", Action.FIND, {"filter": {}}) for _ in range(n))
    )
    elapsed = time.monotonic() - start

    assert all(r["status"] == "success" for r in results)
    assert elapsed < 10.0, f"{n} concurrent find() calls took {elapsed:.2f}s"

    verify = verify_chain(audit_path, "perf-test-secret")
    assert verify.ok, verify
    assert verify.records == n  # every concurrent request got exactly one audit record


@pytest.mark.asyncio
async def test_concurrent_multi_agent_load_stays_isolated_and_fast(tmp_path):
    """Load-shaped: many agents, many concurrent requests each, through the
    REAL pipeline (not just the rate limiter in isolation — see
    test_rate_limit_integration.py for that). No agent's audit trail or
    result should be affected by the others' concurrent load."""
    pipeline, real, audit_path = _pipeline(tmp_path)
    await real["testdb"]["users"].insert_many([{"i": i} for i in range(10)])

    agents = [f"agent-{i}" for i in range(10)]
    calls_per_agent = 10

    async def _run_for(agent):
        return await asyncio.gather(
            *(
                pipeline.run(agent, "users", Action.FIND, {"filter": {}})
                for _ in range(calls_per_agent)
            )
        )

    start = time.monotonic()
    all_results = await asyncio.gather(*(_run_for(a) for a in agents))
    elapsed = time.monotonic() - start

    for agent_results in all_results:
        assert all(r["status"] == "success" for r in agent_results)
    assert elapsed < 15.0, f"{len(agents) * calls_per_agent} concurrent calls took {elapsed:.2f}s"

    verify = verify_chain(audit_path, "perf-test-secret")
    assert verify.ok
    assert verify.records == len(agents) * calls_per_agent


# ── Microbenchmark: pure policy evaluation overhead (no I/O) ───────────────


def test_policy_evaluation_overhead_is_negligible(tmp_path):
    pipeline, _real, _audit_path = _pipeline(tmp_path)
    n = 5000
    start = time.monotonic()
    for _ in range(n):
        pipeline.evaluate("claude", "users", Action.FIND, {"filter": {}})
    elapsed = time.monotonic() - start
    # Pure in-memory policy evaluation, no I/O — should be well under a
    # millisecond each even generously bounded (guards a regression that adds
    # accidental synchronous I/O or O(n) work per evaluate() call).
    assert elapsed < 5.0, f"{n} evaluate() calls took {elapsed:.2f}s"
