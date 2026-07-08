"""S-5: aggregate result materialization is capped at max_limit with a marker."""

from guardmcp.core.models.domain import Action
from guardmcp.plugins.mongodb.executor import MongoExecutor


async def test_aggregate_caps_and_appends_marker(mock_mongo_client):
    col = mock_mongo_client.get_collection("things")
    await col.insert_many([{"i": i} for i in range(15)])

    executor = MongoExecutor(mock_mongo_client, max_limit=10)
    result = await executor.execute("things", Action.AGGREGATE, {"pipeline": [{"$match": {}}]})

    assert isinstance(result, list)
    # 10 capped documents + 1 appended truncation marker
    assert len(result) == 11
    assert result[-1].get("_guardmcp_truncated") is True
    # the 10 real docs precede the marker
    assert all("_guardmcp_truncated" not in d for d in result[:10])


async def test_aggregate_no_marker_when_under_cap(mock_mongo_client):
    col = mock_mongo_client.get_collection("small")
    await col.insert_many([{"i": i} for i in range(5)])

    executor = MongoExecutor(mock_mongo_client, max_limit=10)
    result = await executor.execute("small", Action.AGGREGATE, {"pipeline": [{"$match": {}}]})

    assert len(result) == 5
    assert not any(d.get("_guardmcp_truncated") for d in result if isinstance(d, dict))


async def test_aggregate_capped_by_byte_budget_even_under_doc_count_cap(mock_mongo_client):
    # Well under max_limit (10) by COUNT, but each doc is huge -> byte cap kicks in.
    col = mock_mongo_client.get_collection("bigdocs")
    await col.insert_many([{"i": i, "blob": "x" * 500_000} for i in range(5)])

    executor = MongoExecutor(mock_mongo_client, max_limit=10)
    result = await executor.execute("bigdocs", Action.AGGREGATE, {"pipeline": [{"$match": {}}]})

    assert result[-1].get("_guardmcp_truncated") is True
    assert "response size budget" in result[-1]["_note"]
    assert len(result) < 6  # fewer than 5 real docs + 1 marker


async def test_find_capped_by_byte_budget(mock_mongo_client):
    col = mock_mongo_client.get_collection("bigdocs2")
    await col.insert_many([{"i": i, "blob": "x" * 500_000} for i in range(5)])

    executor = MongoExecutor(mock_mongo_client, max_limit=20)
    result = await executor.execute("bigdocs2", Action.FIND, {"filter": {}, "limit": 20})

    assert result["truncated_by_size"] is True
    assert result["has_more"] is True
    assert len(result["documents"]) < 5
    assert result["count"] == len(result["documents"])
