"""Integration tests — full pipeline with mongomock-motor (no real MongoDB)."""

import pytest

from guardmcp.core.masking.masker import MASK_VALUE
from guardmcp.core.models.domain import Action


@pytest.mark.asyncio
async def test_find_allowed_and_masks_fields(pipeline, mock_mongo_client):
    col = mock_mongo_client.get_collection("customers")
    await col.insert_many(
        [
            {"name": "Alice", "email": "alice@example.com", "password": "secret"},
            {"name": "Bob", "email": "bob@example.com", "password": "hunter2"},
        ]
    )

    result = await pipeline.run("test-agent", "customers", Action.FIND, {"filter": {}, "limit": 10})

    assert result["status"] == "success"
    docs = result["data"]["documents"]
    assert len(docs) == 2
    assert all(d["email"] == MASK_VALUE for d in docs)
    assert all(d["password"] == MASK_VALUE for d in docs)
    assert docs[0]["name"] in {"Alice", "Bob"}


@pytest.mark.asyncio
async def test_denied_collection_rejected(pipeline):
    result = await pipeline.run("test-agent", "payroll", Action.FIND, {"filter": {}})
    assert result["status"] == "denied"
    assert "payroll" in result["reason"]


@pytest.mark.asyncio
async def test_unknown_agent_denied(pipeline):
    result = await pipeline.run("unknown-agent", "customers", Action.FIND, {"filter": {}})
    assert result["status"] == "denied"
    assert "unknown-agent" in result["reason"]


@pytest.mark.asyncio
async def test_write_blocked_in_readonly(pipeline):
    result = await pipeline.run(
        "test-agent", "customers", Action.INSERT_ONE, {"document": {"name": "Eve"}}
    )
    assert result["status"] == "denied"
    assert "readonly" in result["reason"]


@pytest.mark.asyncio
async def test_count_returns_number(pipeline, mock_mongo_client):
    col = mock_mongo_client.get_collection("customers")
    await col.insert_many([{"name": "Alice"}, {"name": "Bob"}])

    result = await pipeline.run("test-agent", "customers", Action.COUNT, {"filter": {}})
    assert result["status"] == "success"
    assert result["data"] == 2


@pytest.mark.asyncio
async def test_discover_collections_filters_by_policy(pipeline, mock_mongo_client):
    # Create collections in mock DB
    for name in ["customers", "orders", "payroll", "employees"]:
        await mock_mongo_client.get_collection(name).insert_one({"_init": True})

    cols = await pipeline.discover_collections("test-agent")
    assert "customers" in cols
    assert "orders" in cols
    assert "payroll" not in cols  # in deny list


@pytest.mark.asyncio
async def test_describe_collection_hides_masked_fields(pipeline, mock_mongo_client):
    col = mock_mongo_client.get_collection("customers")
    await col.insert_one({"name": "Alice", "email": "a@b.com", "age": 30})

    schema = await pipeline.describe_collection("test-agent", "customers")
    assert schema["fields"]["name"] == "string"
    # canonical BSON token (Layer 5): int, not the old "integer" display label
    assert schema["fields"]["age"] == "int"
    assert schema["fields"]["email"] == "masked"


@pytest.mark.asyncio
async def test_describe_blocked_collection_returns_none(pipeline):
    schema = await pipeline.describe_collection("test-agent", "payroll")
    assert schema is None


@pytest.mark.asyncio
async def test_approval_required_then_approved(pipeline, approval_store, mock_mongo_client):
    import asyncio

    # Reload with readwrite + approval gates
    from guardmcp.core.policy.models import ActionPolicy, ApprovalPolicy, CollectionPolicy, Policy

    # patch policy loader to return readwrite policy
    rw_policy = Policy(
        agent="test-agent",
        mode="readwrite",
        collections=CollectionPolicy(allow=["customers"]),
        actions=ActionPolicy(allow=["find", "delete_many"]),
        mask_fields=[],
        approval=ApprovalPolicy(high=False, critical=True),
    )
    pipeline._policies._policies["test-agent"] = rw_policy

    col = mock_mongo_client.get_collection("customers")
    await col.insert_many([{"name": "Alice"}, {"name": "Bob"}])

    async def approve_after_delay():
        await asyncio.sleep(0.1)
        pending = approval_store.list_pending()
        assert len(pending) == 1
        approval_store.resolve(pending[0].approval_id, approved=True)

    task = asyncio.create_task(approve_after_delay())
    result = await pipeline.run("test-agent", "customers", Action.DELETE_MANY, {"filter": {}})
    await task

    assert result["status"] == "success"
    remaining = await col.count_documents({})
    assert remaining == 0
