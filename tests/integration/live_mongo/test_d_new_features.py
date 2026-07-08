"""Section D — this session's newest features, against real MongoDB (least
real-world exercise so far, highest bug risk)."""

from __future__ import annotations

import contextvars

import pytest

from guardmcp.core import metrics
from guardmcp.core.models.domain import Action

from .conftest import build_pipeline, multi_db_policy, readwrite_masked_policy
from .helpers import call, make_mcp

# ── Cost→risk escalation against a REAL explain (real COLLSCAN) ────────────


@pytest.mark.asyncio
async def test_cost_escalation_on_real_collection_scan(tmp_path, mongo_uri, db_name):
    policy_yaml = """
agent: claude
mode: readwrite
collections:
  allow: ["*"]
max_cost: HIGH
approval:
  high: true
  critical: true
"""
    pipeline, registry, _ = build_pipeline(tmp_path, mongo_uri, db_name, policy_yaml)
    executor = registry.get("default").executor
    await executor._client.get_collection("users").insert_many(
        [{"name": f"u{i}", "unindexed_field": i} for i in range(20)]
    )

    # FIND's base risk is LOW, but max_cost=HIGH + a real COLLSCAN must
    # escalate it enough to require approval.
    result = await pipeline.run(
        "claude", "users", Action.FIND, {"filter": {"unindexed_field": {"$gt": 5}}}
    )
    # Never confirmed -> approval times out -> denied. The key assertion is
    # that it did NOT just succeed silently at LOW risk.
    assert result["status"] in ("denied", "error")


@pytest.mark.asyncio
async def test_no_max_cost_never_escalates(tmp_path, mongo_uri, db_name):
    pipeline, registry, _ = build_pipeline(
        tmp_path, mongo_uri, db_name, readwrite_masked_policy(mask_fields=[])
    )
    executor = registry.get("default").executor
    await executor._client.get_collection("users").insert_many(
        [{"name": f"u{i}"} for i in range(20)]
    )
    result = await pipeline.run("claude", "users", Action.FIND, {"filter": {}})
    assert result["status"] == "success"  # no max_cost -> zero I/O, unaffected


# ── Per-connection active database — real multi-connection, concurrent ────


@pytest.mark.asyncio
async def test_per_connection_active_database_isolation_real(tmp_path, mongo_uri, db_name):
    other_db = f"{db_name}_other"
    pipeline, registry, _ = build_pipeline(
        tmp_path, mongo_uri, db_name,
        readwrite_masked_policy(mask_fields=[]),
        extra_connections={"analytics": other_db},
    )
    assert registry.switch("analytics") is True
    registry.set_active_database("reporting")
    assert registry.get_active_database() == "reporting"

    assert registry.switch("default") is True
    assert registry.get_active_database() is None  # "default" never had one set

    assert registry.switch("analytics") is True
    assert registry.get_active_database() == "reporting"  # restored


def test_active_database_isolated_across_concurrent_contexts_real(tmp_path):
    from guardmcp.core.registry.connections import ConnectionEntry, ConnectionRegistry, reset_active

    reset_active()
    reg = ConnectionRegistry()
    reg._registry["default"] = ConnectionEntry(client=None, database="d")

    observed = {}

    def _run(db, key):
        reg.set_active_database(db)
        observed[key] = reg.get_active_database()

    ctx_a = contextvars.copy_context()
    ctx_b = contextvars.copy_context()
    ctx_a.run(_run, "identity", "a")
    ctx_b.run(_run, "inventory", "b")

    assert observed == {"a": "identity", "b": "inventory"}
    assert reg.get_active_database() is None
    reset_active()


# ── Cross-DB relationships + data-trust signals vs REAL sampled data ───────


@pytest.mark.asyncio
async def test_cross_db_edges_and_data_trust_signals_real(tmp_path, mongo_uri, db_name):
    db2 = f"{db_name}_b"
    policy_yaml = multi_db_policy(
        databases_allow=[db_name, db2],
        per_db_mask={db_name: ["nothing_masked_here"], db2: ["nothing_masked_here"]},
    )
    pipeline, registry, _ = build_pipeline(
        tmp_path, mongo_uri, db_name, policy_yaml, extra_connections={"b": db2}
    )
    default_client = registry.get("default").executor._client
    b_client = registry.get("b").executor._client

    # Shared id-shaped field across two databases -> cross-db edge candidate.
    await default_client.get_collection("identity").insert_many(
        [{"account_id": "acc1"}, {"account_id": "acc2"}]
    )
    await b_client.get_collection("inventory").insert_many(
        [{"account_id": "acc1"}, {"account_id": "acc2"}]
    )

    mcp = make_mcp(pipeline)
    out = await call(mcp, "guardmcp_relationships")
    assert out["ok"] is True
    assert "cross_db_edges" in out["data"]

    # Data-trust signals: a real timestamp field with real null/non-null mix.
    await default_client.get_collection("events").insert_many(
        [{"created_at": None}, {"created_at": "2026-01-01T00:00:00"}]
    )
    schema_out = await call(mcp, "db_schema", collection="events")
    assert schema_out["ok"] is True


# ── Byte-budget truncation vs a REAL large document ─────────────────────────


@pytest.mark.asyncio
async def test_byte_budget_truncation_real_large_document(tmp_path, mongo_uri, db_name):
    pipeline, registry, _ = build_pipeline(
        tmp_path, mongo_uri, db_name, readwrite_masked_policy(mask_fields=[])
    )
    executor = registry.get("default").executor
    await executor._client.get_collection("blobs").insert_many(
        [{"i": i, "blob": "x" * 500_000} for i in range(5)]
    )
    out = await pipeline.run("claude", "blobs", Action.FIND, {"filter": {}, "limit": 20})
    assert out["status"] == "success"
    assert out["data"]["truncated_by_size"] is True
    assert len(out["data"]["documents"]) < 5


# ── /metrics real accumulation ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_metrics_accumulate_over_real_calls(tmp_path, mongo_uri, db_name):
    metrics.reset()
    pipeline, registry, _ = build_pipeline(
        tmp_path, mongo_uri, db_name, readwrite_masked_policy(mask_fields=[])
    )
    executor = registry.get("default").executor
    await executor._client.get_collection("users").insert_one({"x": 1})

    for _ in range(3):
        await pipeline.run("claude", "users", Action.FIND, {"filter": {}})

    rendered = metrics.render_prometheus()
    assert 'guardmcp_requests_total{action="find",status="allowed"} 3' in rendered
