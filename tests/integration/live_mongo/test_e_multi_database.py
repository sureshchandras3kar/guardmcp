"""Section E — multi-database & multi-connection, real MongoDB (one
container, several logical databases — cheap to set up for real)."""

from __future__ import annotations

import pytest

from guardmcp.core.models.domain import Action

from .conftest import build_pipeline, multi_db_policy
from .helpers import call, make_mcp

# ── databases_allow gate ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_databases_allow_gate_denies_non_allowed_database(tmp_path, mongo_uri, db_name):
    other_db = f"{db_name}_other"
    policy_yaml = multi_db_policy(databases_allow=[db_name])  # other_db NOT allowed
    pipeline, _, _ = build_pipeline(tmp_path, mongo_uri, db_name, policy_yaml)

    allowed = await pipeline.run("claude", "users", Action.FIND, {"filter": {}}, database=db_name)
    assert allowed["status"] == "success"

    denied = await pipeline.run(
        "claude", "users", Action.FIND, {"filter": {}}, database=other_db
    )
    assert denied["status"] == "denied"
    assert denied["code"] == "DATABASE_NOT_ALLOWED"


# ── per-DB mask_fields / collection scope ───────────────────────────────────


@pytest.mark.asyncio
async def test_per_database_mask_fields_independent(tmp_path, mongo_uri, db_name):
    db_b = f"{db_name}_b"
    policy_yaml = multi_db_policy(
        databases_allow=[db_name, db_b],
        per_db_mask={db_name: ["ssn"], db_b: ["email"]},
    )
    pipeline, registry, _ = build_pipeline(
        tmp_path, mongo_uri, db_name, policy_yaml, extra_connections={"b": db_b}
    )
    default_client = registry.get("default").executor._client
    doc = {"ssn": "111-22-3333", "email": "a@b.com"}
    await default_client.get_collection("user").insert_one(dict(doc))
    # Same collection NAME, different physical database (via the "b" connection).
    b_client = registry.get("b").executor._client
    await b_client.get_collection("user").insert_one(dict(doc))

    out_a = await pipeline.run("claude", "user", Action.FIND, {"filter": {}}, database=db_name)
    doc_a = out_a["data"]["documents"][0]
    assert doc_a["ssn"] == "***masked***"
    assert doc_a["email"] == "a@b.com"  # NOT masked in db_name's scope

    out_b = await pipeline.run("claude", "user", Action.FIND, {"filter": {}}, database=db_b)
    doc_b = out_b["data"]["documents"][0]
    assert doc_b["email"] == "***masked***"
    assert doc_b["ssn"] == "111-22-3333"  # NOT masked in db_b's scope


# ── _guard_aggregation is per-database (re-verify the doc-staleness finding) ─


@pytest.mark.asyncio
async def test_guard_aggregation_is_per_database_real(tmp_path, mongo_uri, db_name):
    db_b = f"{db_name}_b"
    # db_name allows "orders" + "payroll"; db_b allows "orders" only.
    policy_yaml = f"""
agent: claude
mode: readwrite
collections:
  allow: ["*"]
databases_allow:
  - {db_name}
  - {db_b}
databases:
  {db_name}:
    collections:
      allow: ["orders", "payroll"]
  {db_b}:
    collections:
      allow: ["orders"]
approval:
  high: false
  critical: false
"""
    pipeline, registry, _ = build_pipeline(
        tmp_path, mongo_uri, db_name, policy_yaml, extra_connections={"b": db_b}
    )
    default_client = registry.get("default").executor._client
    await default_client.get_collection("orders").insert_one({"amount": 1})
    b_client = registry.get("b").executor._client
    await b_client.get_collection("orders").insert_one({"amount": 1})

    lookup_pipeline = [
        {
            "$lookup": {
                "from": "payroll", "localField": "amount",
                "foreignField": "amount", "as": "p",
            }
        }
    ]

    # Allowed in db_name's scope (payroll is allowed there).
    ok_out = await pipeline.run(
        "claude", "orders", Action.AGGREGATE, {"pipeline": lookup_pipeline}, database=db_name
    )
    assert ok_out["status"] == "success"

    # DENIED in db_b's scope (payroll is NOT in db_b's collection allow-list) —
    # this is exactly the per-database aggregation guard scope check.
    denied_out = await pipeline.run(
        "claude", "orders", Action.AGGREGATE, {"pipeline": lookup_pipeline}, database=db_b
    )
    assert denied_out["status"] == "denied"
    assert denied_out["code"] == "COLLECTION_NOT_ALLOWED"


# ── Tool-layer switch_connection + use_database interplay ──────────────────


@pytest.mark.asyncio
async def test_switch_connection_and_use_database_interplay_tool_layer(
    tmp_path, mongo_uri, db_name
):
    db_b = f"{db_name}_reporting"
    policy_yaml = multi_db_policy(databases_allow=[db_name, db_b])
    pipeline, registry, _ = build_pipeline(
        tmp_path, mongo_uri, db_name, policy_yaml, extra_connections={"analytics": db_b}
    )
    default_client = registry.get("default").executor._client
    await default_client.get_collection("users").insert_one({"x": 1})
    analytics_client = registry.get("analytics").executor._client
    await analytics_client.get_collection("users").insert_one({"x": 2})
    await analytics_client.get_collection("users").insert_one({"x": 3})

    mcp = make_mcp(pipeline)

    # On default connection, no use_database set -> resolves to connection default.
    out1 = await call(mcp, "db_find", collection="users", filter={})
    assert len(out1["data"]["documents"]) == 1

    # Switch to "analytics" connection.
    switch_out = await call(mcp, "db_switch_connection", connection_name="analytics")
    assert switch_out["ok"] is True

    out2 = await call(mcp, "db_find", collection="users", filter={})
    assert len(out2["data"]["documents"]) == 2  # analytics connection's own default db

    # Switch back to default -> its own remembered state (none set) restored.
    await call(mcp, "db_switch_connection", connection_name="default")
    out3 = await call(mcp, "db_find", collection="users", filter={})
    assert len(out3["data"]["documents"]) == 1  # NOT leaked from analytics
