"""Integration tests for the 11 priority features."""

import pytest

from guardmcp.core.masking.masker import MASK_VALUE
from guardmcp.core.models.domain import Action

# ── collection_schema ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_collection_schema_infers_types(pipeline, mock_mongo_client):
    col = mock_mongo_client.get_collection("customers")
    await col.insert_many(
        [
            {"name": "Alice", "email": "a@b.com", "age": 30},
            {"name": "Bob", "email": "b@c.com", "age": 25},
        ]
    )
    result = await pipeline.run("test-agent", "customers", Action.COLLECTION_SCHEMA, {})
    assert result["status"] == "success"
    fields = result["data"]
    assert fields["name"] == "string"
    # canonical BSON token (Layer 5): int, not the old "integer" display label
    assert fields["age"] == "int"
    # email is in mask_fields → must appear as "masked"
    assert fields["email"] == "masked"


@pytest.mark.asyncio
async def test_collection_schema_blocked_collection(pipeline):
    result = await pipeline.run("test-agent", "payroll", Action.COLLECTION_SCHEMA, {})
    assert result["status"] == "denied"


# ── explain ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.xfail(reason="mongomock-motor does not support cursor.explain()")
async def test_explain_find_returns_plan(pipeline, mock_mongo_client):
    col = mock_mongo_client.get_collection("customers")
    await col.insert_one({"name": "Alice"})
    result = await pipeline.run(
        "test-agent",
        "customers",
        Action.EXPLAIN,
        {"mode": "find", "filter": {"name": "Alice"}},
    )
    # mongomock returns a basic explain structure
    assert result["status"] == "success"
    assert "data" in result


# ── list_databases ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_databases_allowed(pipeline):
    result = await pipeline.run("test-agent", "", Action.LIST_DATABASES, {})
    assert result["status"] == "success"
    assert "data" in result


# ── db_stats ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.xfail(reason="mongomock-motor does not support db.command('dbStats')")
async def test_db_stats_returns_data(pipeline):
    result = await pipeline.run("test-agent", "", Action.DB_STATS, {})
    assert result["status"] == "success"


# ── collection_indexes ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_collection_indexes_returns_list(pipeline, mock_mongo_client):
    col = mock_mongo_client.get_collection("customers")
    await col.insert_one({"name": "Alice"})
    result = await pipeline.run("test-agent", "customers", Action.COLLECTION_INDEXES, {})
    assert result["status"] == "success"
    indexes = result["data"]
    assert isinstance(indexes, list)
    # _id index always exists
    assert any(idx["name"] == "_id_" for idx in indexes)


# ── find with pagination (skip + limit) ───────────────────────────────────────


@pytest.mark.asyncio
async def test_find_pagination(pipeline, mock_mongo_client):
    col = mock_mongo_client.get_collection("customers")
    await col.insert_many([{"name": f"User{i}"} for i in range(10)])

    # Page 1
    r1 = await pipeline.run(
        "test-agent", "customers", Action.FIND, {"filter": {}, "limit": 3, "skip": 0}
    )
    assert r1["status"] == "success"
    assert r1["data"]["count"] == 3
    assert r1["data"]["has_more"] is True
    assert r1["data"]["next_skip"] == 3

    # Page 2
    r2 = await pipeline.run(
        "test-agent", "customers", Action.FIND, {"filter": {}, "limit": 3, "skip": 3}
    )
    assert r2["data"]["skip"] == 3
    assert r2["data"]["count"] == 3

    # Verify no overlap
    names1 = {d["name"] for d in r1["data"]["documents"]}
    names2 = {d["name"] for d in r2["data"]["documents"]}
    assert names1 & names2 == set()


@pytest.mark.asyncio
async def test_find_last_page_has_more_false(pipeline, mock_mongo_client):
    col = mock_mongo_client.get_collection("customers")
    await col.insert_many([{"name": f"U{i}"} for i in range(5)])

    r = await pipeline.run(
        "test-agent", "customers", Action.FIND, {"filter": {}, "limit": 10, "skip": 0}
    )
    assert r["data"]["has_more"] is False
    assert r["data"]["count"] == 5


# ── insert_many ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_insert_many_blocked_in_readonly(pipeline):
    docs = [{"name": "A"}, {"name": "B"}]
    result = await pipeline.run("test-agent", "customers", Action.INSERT_MANY, {"documents": docs})
    assert result["status"] == "denied"
    assert "readonly" in result["reason"]


# ── create_index ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_index_blocked_in_readonly(pipeline):
    result = await pipeline.run(
        "test-agent", "customers", Action.CREATE_INDEX, {"keys": [["name", 1]], "options": {}}
    )
    assert result["status"] == "denied"


# ── evaluate / execute_approved split (for in-band elicit) ────────────────────


@pytest.mark.asyncio
async def test_evaluate_returns_allowed_for_find(pipeline):
    eval_result = pipeline.evaluate("test-agent", "customers", Action.FIND, {"filter": {}})
    from guardmcp.core.models.domain import DecisionStatus

    assert eval_result.decision.status == DecisionStatus.ALLOWED


@pytest.mark.asyncio
async def test_evaluate_returns_denied_for_blocked_collection(pipeline):
    eval_result = pipeline.evaluate("test-agent", "payroll", Action.FIND, {})
    from guardmcp.core.models.domain import DecisionStatus

    assert eval_result.decision.status == DecisionStatus.DENIED


@pytest.mark.asyncio
async def test_execute_approved_runs_query(pipeline, mock_mongo_client):
    col = mock_mongo_client.get_collection("customers")
    await col.insert_one({"name": "Alice", "email": "a@b.com"})

    eval_result = pipeline.evaluate(
        "test-agent", "customers", Action.FIND, {"filter": {}, "limit": 10}
    )
    result = await pipeline.execute_approved(eval_result)
    assert result["status"] == "success"
    docs = result["data"]["documents"]
    assert len(docs) == 1
    assert docs[0]["email"] == MASK_VALUE  # masking still applied


# ── index scan enforcement ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_index_scan_enforcement_blocks_unindexed(mock_mongo_client):
    from guardmcp.plugins.mongodb.executor import MongoExecutor

    col = mock_mongo_client.get_collection("customers")
    await col.insert_one({"name": "Alice", "unindexed_field": "x"})

    executor = MongoExecutor(mock_mongo_client, enforce_index_usage=True)
    with pytest.raises(ValueError, match="no covering index"):
        await executor.enforce_index_for_find("customers", {"unindexed_field": "x"})


@pytest.mark.asyncio
async def test_index_scan_enforcement_passes_for_id(mock_mongo_client):
    from guardmcp.plugins.mongodb.executor import MongoExecutor

    executor = MongoExecutor(mock_mongo_client, enforce_index_usage=True)
    # _id always has an index — should not raise
    await executor.enforce_index_for_find("customers", {"_id": "some_id"})


@pytest.mark.asyncio
async def test_index_scan_enforcement_disabled_by_default(mock_mongo_client):
    from guardmcp.plugins.mongodb.executor import MongoExecutor

    executor = MongoExecutor(mock_mongo_client, enforce_index_usage=False)
    # enforce_index_usage=False → should never raise
    await executor.enforce_index_for_find("customers", {"any_field": "x"})
