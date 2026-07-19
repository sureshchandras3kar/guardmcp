"""Section A — golden path / core governance, against REAL MongoDB (no
mongomock). These are the invariants that must hold regardless of any new
feature added this session.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from bson import Decimal128, ObjectId

from guardmcp.core.audit.verify import verify_chain
from guardmcp.core.masking.masker import MASK_VALUE
from guardmcp.core.models.domain import Action, DecisionStatus

from .conftest import build_pipeline, readonly_allow_all_policy, readwrite_masked_policy

# ── Deny-by-default ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_allow_list_denies_everything(tmp_path, mongo_uri, db_name):
    policy_yaml = "agent: claude\nmode: readonly\ncollections:\n  allow: []\n"
    pipeline, _, _ = build_pipeline(tmp_path, mongo_uri, db_name, policy_yaml)
    out = await pipeline.run("claude", "users", Action.FIND, {"filter": {}})
    assert out["status"] == "denied"


# ── readonly blocks writes, allows reads ────────────────────────────────────


@pytest.mark.asyncio
async def test_readonly_blocks_write_allows_read(tmp_path, mongo_uri, db_name):
    pipeline, registry, _ = build_pipeline(
        tmp_path, mongo_uri, db_name, readonly_allow_all_policy()
    )
    executor = registry.get("default").executor
    await executor._client.get_collection("users").insert_one({"name": "seed"})

    write_out = await pipeline.run(
        "claude", "users", Action.INSERT_ONE, {"document": {"name": "x"}}
    )
    assert write_out["status"] == "denied"
    assert write_out["code"] == "READONLY"

    read_out = await pipeline.run("claude", "users", Action.FIND, {"filter": {}})
    assert read_out["status"] == "success"
    assert len(read_out["data"]["documents"]) == 1


# ── Field masking at any nesting depth ──────────────────────────────────────


@pytest.mark.asyncio
async def test_masking_recursive_at_nested_depth(tmp_path, mongo_uri, db_name):
    pipeline, registry, _ = build_pipeline(
        tmp_path, mongo_uri, db_name,
        readwrite_masked_policy(mask_fields=["ssn"]),
    )
    executor = registry.get("default").executor
    await executor._client.get_collection("users").insert_one(
        {
            "name": "Ada",
            "ssn": "111-22-3333",
            "profile": {"contact": {"ssn": "444-55-6666"}},
            "history": [{"event": "signup", "ssn": "777-88-9999"}],
        }
    )
    out = await pipeline.run("claude", "users", Action.FIND, {"filter": {}})
    assert out["status"] == "success"
    doc = out["data"]["documents"][0]
    assert doc["ssn"] == MASK_VALUE
    # Masking is key-name based recursively — nested/array occurrences too.
    assert doc["profile"]["contact"]["ssn"] == MASK_VALUE
    assert doc["history"][0]["ssn"] == MASK_VALUE
    assert "111-22-3333" not in str(out)
    assert "444-55-6666" not in str(out)
    assert "777-88-9999" not in str(out)


# ── Aggregation guard ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_aggregation_guard_blocks_lookup_to_denied_collection(tmp_path, mongo_uri, db_name):
    policy_yaml = """
agent: claude
mode: readonly
collections:
  allow: [orders]
  deny: [payroll]
"""
    pipeline, registry, _ = build_pipeline(tmp_path, mongo_uri, db_name, policy_yaml)
    executor = registry.get("default").executor
    await executor._client.get_collection("orders").insert_one({"amount": 10})

    out = await pipeline.run(
        "claude", "orders", Action.AGGREGATE,
        {
            "pipeline": [
                {
                    "$lookup": {
                        "from": "payroll", "localField": "amount",
                        "foreignField": "amount", "as": "p",
                    }
                }
            ]
        },
    )
    assert out["status"] == "denied"
    assert out["code"] == "COLLECTION_NOT_ALLOWED"


@pytest.mark.asyncio
async def test_aggregation_guard_blocks_masked_field_aliasing(tmp_path, mongo_uri, db_name):
    pipeline, registry, _ = build_pipeline(
        tmp_path, mongo_uri, db_name,
        readwrite_masked_policy(collections_allow=["users"], mask_fields=["email"]),
    )
    executor = registry.get("default").executor
    await executor._client.get_collection("users").insert_one({"email": "a@b.com"})

    out = await pipeline.run(
        "claude", "users", Action.AGGREGATE,
        {"pipeline": [{"$project": {"x": "$email"}}]},
    )
    assert out["status"] == "denied"


# ── Risk -> approval: confirm executes, decline never executes ─────────────


@pytest.mark.asyncio
async def test_critical_write_requires_approval_and_executes_when_confirmed(
    tmp_path, mongo_uri, db_name
):
    pipeline, registry, _ = build_pipeline(
        tmp_path, mongo_uri, db_name,
        readwrite_masked_policy(collections_allow=["orders"], mask_fields=[]),
    )
    executor = registry.get("default").executor
    await executor._client.get_collection("orders").insert_many(
        [{"_id": 1, "status": "open"}, {"_id": 2, "status": "open"}]
    )

    eval_result = pipeline.evaluate("claude", "orders", Action.DELETE_MANY, {"filter": {}})
    assert eval_result.decision.status == DecisionStatus.APPROVAL_REQUIRED

    # Confirmed: execute_approved runs the ALREADY-EVALUATED request.
    result = await pipeline.execute_approved(eval_result)
    assert result["status"] == "success"

    remaining = await pipeline.run("claude", "orders", Action.FIND, {"filter": {}})
    assert remaining["data"]["documents"] == []


@pytest.mark.asyncio
async def test_critical_write_declined_never_executes(tmp_path, mongo_uri, db_name):
    pipeline, registry, _ = build_pipeline(
        tmp_path, mongo_uri, db_name,
        readwrite_masked_policy(collections_allow=["orders"], mask_fields=[]),
    )
    executor = registry.get("default").executor
    await executor._client.get_collection("orders").insert_one({"_id": 1, "status": "open"})

    eval_result = pipeline.evaluate("claude", "orders", Action.DELETE_MANY, {"filter": {}})
    assert eval_result.decision.status == DecisionStatus.APPROVAL_REQUIRED
    # Declined: caller simply never calls execute_approved.

    remaining = await pipeline.run("claude", "orders", Action.FIND, {"filter": {}})
    assert len(remaining["data"]["documents"]) == 1  # untouched


# ── Audit chain integrity ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_audit_chain_verifies_after_a_full_run(tmp_path, mongo_uri, db_name):
    pipeline, registry, audit_path = build_pipeline(
        tmp_path, mongo_uri, db_name, readwrite_masked_policy(collections_allow=["orders"])
    )
    executor = registry.get("default").executor
    await executor._client.get_collection("orders").insert_one({"_id": 1})

    for _ in range(5):
        await pipeline.run("claude", "orders", Action.FIND, {"filter": {}})

    result = verify_chain(audit_path, "livetest-secret")
    assert result.ok, result
    assert result.records == 5


# ── Type marshalling against REAL BSON types ────────────────────────────────


@pytest.mark.asyncio
async def test_type_marshalling_date_objectid_decimal_real_bson(tmp_path, mongo_uri, db_name):
    pipeline, registry, _ = build_pipeline(
        tmp_path, mongo_uri, db_name, readwrite_masked_policy(collections_allow=["orders"])
    )
    executor = registry.get("default").executor
    oid = ObjectId()
    created = datetime(2026, 1, 1, tzinfo=UTC)
    await executor._client.get_collection("orders").insert_one(
        {
            "_id": oid,
            "created_at": created,
            "amount": Decimal128("19.99"),
        }
    )

    # Real BSON date field, filtered with an ISO string — must coerce, not
    # silently return empty (this is the class of bug mongomock can hide).
    out = await pipeline.run(
        "claude", "orders", Action.FIND,
        {"filter": {"created_at": {"$gte": "2025-12-31"}}},
    )
    assert out["status"] == "success"
    assert len(out["data"]["documents"]) == 1

    # ObjectId literal filter via extended-JSON escape hatch.
    out2 = await pipeline.run(
        "claude", "orders", Action.FIND,
        {"filter": {"_id": {"$oid": str(oid)}}},
    )
    assert out2["status"] == "success"
    assert len(out2["data"]["documents"]) == 1
