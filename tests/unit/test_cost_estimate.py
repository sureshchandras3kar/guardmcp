"""Feature 1 — Query Cost Estimation unit tests.

Covers the frozen CostEstimate model, the shared classify_cost heuristic, the
DatabasePlugin default estimate(), per-backend normalization (Mongo / Postgres /
MySQL) from canned explain payloads, and the RiskEngine cost escalation hook.
No live DB is used anywhere here.
"""

from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from guardmcp.core.interfaces.capability import Capability, CapabilityRequest
from guardmcp.core.interfaces.cost import CostEstimate, CostLevel, classify_cost
from guardmcp.core.interfaces.plugin import DatabasePlugin
from guardmcp.core.models.domain import RiskLevel
from guardmcp.core.risk.engine import RiskEngine
from guardmcp.plugins.mongodb.cost import normalize_mongo_explain
from guardmcp.plugins.sql.cost import (
    normalize_mysql_explain,
    normalize_postgres_explain,
)

# ── CostEstimate model ──────────────────────────────────────────────────────


def test_cost_estimate_defaults():
    est = CostEstimate()
    assert est.estimated_documents is None
    assert est.estimated_keys_examined is None
    assert est.collection_scan is None
    assert est.index_used is None
    assert est.estimated_cost is CostLevel.UNKNOWN
    assert est.estimated_duration_ms is None
    assert est.warnings == []


def test_cost_estimate_is_frozen():
    est = CostEstimate(estimated_cost=CostLevel.LOW)
    with pytest.raises(ValidationError):
        est.estimated_cost = CostLevel.HIGH


# ── classify_cost heuristic ─────────────────────────────────────────────────


def test_classify_no_signal_is_unknown():
    assert (
        classify_cost(estimated_documents=None, collection_scan=None, index_used=None)
        is CostLevel.UNKNOWN
    )


def test_classify_collection_scan_is_high():
    assert (
        classify_cost(estimated_documents=50, collection_scan=True, index_used=False)
        is CostLevel.HIGH
    )


def test_classify_collection_scan_large_is_critical():
    assert (
        classify_cost(estimated_documents=2_000_000, collection_scan=True, index_used=False)
        is CostLevel.CRITICAL
    )


def test_classify_indexed_small_is_low():
    assert (
        classify_cost(estimated_documents=3, collection_scan=False, index_used=True)
        is CostLevel.LOW
    )


def test_classify_indexed_large_is_high():
    assert (
        classify_cost(estimated_documents=50_000, collection_scan=False, index_used=True)
        is CostLevel.HIGH
    )


def test_classify_indexed_medium_volume():
    assert (
        classify_cost(estimated_documents=5_000, collection_scan=False, index_used=True)
        is CostLevel.MEDIUM
    )


# ── DatabasePlugin default estimate() ───────────────────────────────────────


class _BarePlugin(DatabasePlugin):
    name = "bare"
    supported = frozenset()

    async def connect(self, dsn, options): ...
    async def health(self):
        return True

    async def close(self): ...
    async def execute(self, req): ...
    async def schema(self, resource, sample_size=None):
        return {}

    async def list_resources(self):
        return []

    def validate_request(self, req): ...


def test_default_estimate_returns_unknown_with_warning():
    plugin = _BarePlugin()
    req = CapabilityRequest(capability=Capability.READ, resource="t")
    est = asyncio.run(plugin.estimate(req))
    assert est.estimated_cost is CostLevel.UNKNOWN
    assert est.warnings == ["estimation not supported by this backend"]


# ── Mongo normalization ─────────────────────────────────────────────────────


def _mongo_explain(stage: str, docs: int, keys: int, n: int, ms: int) -> dict:
    return {
        "queryPlanner": {"winningPlan": {"stage": stage}},
        "executionStats": {
            "totalDocsExamined": docs,
            "totalKeysExamined": keys,
            "nReturned": n,
            "executionTimeMillis": ms,
        },
    }


def test_mongo_collscan_normalizes_to_high():
    est = normalize_mongo_explain(_mongo_explain("COLLSCAN", 5000, 0, 5000, 12))
    assert est.collection_scan is True
    assert est.index_used is False
    assert est.estimated_documents == 5000
    assert est.estimated_cost is CostLevel.HIGH
    assert est.estimated_duration_ms == 12
    assert any("collection scan" in w for w in est.warnings)


def test_mongo_ixscan_normalizes_to_low():
    explain = {
        "queryPlanner": {"winningPlan": {"stage": "FETCH", "inputStage": {"stage": "IXSCAN"}}},
        "executionStats": {
            "totalDocsExamined": 1,
            "totalKeysExamined": 1,
            "nReturned": 1,
            "executionTimeMillis": 0,
        },
    }
    est = normalize_mongo_explain(explain)
    assert est.index_used is True
    assert est.collection_scan is False
    assert est.estimated_documents == 1
    assert est.estimated_cost is CostLevel.LOW
    assert est.warnings == []


def test_mongo_does_not_leak_raw_plan():
    # The CostEstimate has NO field that could carry the raw plan dict.
    est = normalize_mongo_explain(_mongo_explain("COLLSCAN", 5000, 0, 5000, 12))
    dumped = est.model_dump()
    assert "winningPlan" not in str(dumped)
    assert "executionStats" not in str(dumped)


# ── Postgres normalization ──────────────────────────────────────────────────


def test_postgres_seq_scan_is_scan():
    payload = [{"Plan": {"Node Type": "Seq Scan", "Plan Rows": 20000, "Total Cost": 431.0}}]
    est = normalize_postgres_explain(payload)
    assert est.collection_scan is True
    assert est.index_used is False
    assert est.estimated_documents == 20000
    assert est.estimated_cost is CostLevel.HIGH


def test_postgres_index_scan_is_index():
    payload = [{"Plan": {"Node Type": "Index Scan", "Plan Rows": 1, "Total Cost": 8.3}}]
    est = normalize_postgres_explain(payload)
    assert est.index_used is True
    assert est.collection_scan is False
    assert est.estimated_documents == 1
    assert est.estimated_cost is CostLevel.LOW


# ── MySQL normalization ─────────────────────────────────────────────────────


def test_mysql_all_access_is_scan():
    payload = {"query_block": {"table": {"access_type": "ALL", "rows_examined_per_scan": 15000}}}
    est = normalize_mysql_explain(payload)
    assert est.collection_scan is True
    assert est.index_used is False
    assert est.estimated_documents == 15000
    assert est.estimated_cost is CostLevel.HIGH


def test_mysql_ref_access_is_index():
    payload = {"query_block": {"table": {"access_type": "ref", "rows_examined_per_scan": 2}}}
    est = normalize_mysql_explain(payload)
    assert est.index_used is True
    assert est.collection_scan is False
    assert est.estimated_documents == 2
    assert est.estimated_cost is CostLevel.LOW


# ── RiskEngine cost escalation hook ─────────────────────────────────────────


def test_escalate_for_cost_bumps_on_high():
    engine = RiskEngine()
    bumped = engine.escalate_for_cost(RiskLevel.LOW, CostEstimate(estimated_cost=CostLevel.HIGH))
    assert bumped is RiskLevel.HIGH


def test_escalate_for_cost_critical():
    engine = RiskEngine()
    bumped = engine.escalate_for_cost(
        RiskLevel.MEDIUM, CostEstimate(estimated_cost=CostLevel.CRITICAL)
    )
    assert bumped is RiskLevel.CRITICAL


def test_escalate_for_cost_does_not_downgrade():
    engine = RiskEngine()
    # base already CRITICAL, cost only HIGH → stays CRITICAL.
    kept = engine.escalate_for_cost(RiskLevel.CRITICAL, CostEstimate(estimated_cost=CostLevel.HIGH))
    assert kept is RiskLevel.CRITICAL


def test_escalate_for_cost_unknown_is_noop():
    engine = RiskEngine()
    kept = engine.escalate_for_cost(RiskLevel.LOW, CostEstimate(estimated_cost=CostLevel.UNKNOWN))
    assert kept is RiskLevel.LOW


# ── MongoPlugin.estimate via fake executor (no live DB) ─────────────────────


class _FakeMongoExecutor:
    """Returns a canned explain(executionStats) dict for find."""

    def __init__(self, explain: dict):
        self._explain = explain
        self.calls: list[tuple] = []

    async def explain_find_stats(self, collection, filter_, projection=None):
        self.calls.append((collection, filter_, projection))
        return self._explain

    async def explain_aggregate_stats(self, collection, pipeline):
        self.calls.append((collection, pipeline))
        return self._explain


def test_mongo_plugin_estimate_collscan():
    from guardmcp.plugins.mongodb.plugin import MongoPlugin

    fake = _FakeMongoExecutor(_mongo_explain("COLLSCAN", 8000, 0, 8000, 30))
    plugin = MongoPlugin(executor=fake)
    req = CapabilityRequest(capability=Capability.READ, resource="user", filter={"city": "X"})
    est = asyncio.run(plugin.estimate(req))
    assert est.collection_scan is True
    assert est.estimated_cost is CostLevel.HIGH
    assert fake.calls and fake.calls[0][0] == "user"


def test_mongo_plugin_estimate_failure_is_unknown():
    from guardmcp.plugins.mongodb.plugin import MongoPlugin

    class _Boom:
        async def explain_find_stats(self, *a, **k):
            raise RuntimeError("boom")

    plugin = MongoPlugin(executor=_Boom())
    req = CapabilityRequest(capability=Capability.READ, resource="user")
    est = asyncio.run(plugin.estimate(req))
    assert est.estimated_cost is CostLevel.UNKNOWN
    assert any("explain failed" in w for w in est.warnings)


def test_adapter_estimate_delegates_to_plugin():
    from guardmcp.core.registry.adapter import CapabilityExecutorAdapter

    sentinel = CostEstimate(estimated_cost=CostLevel.MEDIUM, warnings=["from-plugin"])

    class _P(_BarePlugin):
        async def estimate(self, req):
            return sentinel

    adapter = CapabilityExecutorAdapter(_P())
    req = CapabilityRequest(capability=Capability.READ, resource="t")
    est = asyncio.run(adapter.estimate(req))
    assert est is sentinel
