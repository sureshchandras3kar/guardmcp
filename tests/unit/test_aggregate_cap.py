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
