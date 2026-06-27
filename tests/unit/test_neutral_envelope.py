"""#6: backend-neutral success envelope — Mongo native results ALSO expose
rows/affected/scalar uniformly, additively (native keys remain intact)."""

import json

import pytest

from guardmcp.core.models.domain import Action
from guardmcp.core.neutral import neutralize
from guardmcp.server.responses import from_pipeline_result


def test_neutralize_find():
    data = {"documents": [{"a": 1}], "count": 1, "skip": 0, "limit": 20}
    n = neutralize(Action.FIND, data)
    assert n["rows"] == [{"a": 1}]
    assert n["scalar"] == 1
    assert n["affected"] is None


def test_neutralize_count():
    n = neutralize(Action.COUNT, 7)
    assert n["scalar"] == 7
    assert n["rows"] == []


def test_neutralize_insert_one():
    n = neutralize(Action.INSERT_ONE, {"inserted_id": "abc"})
    assert n["affected"] == 1


def test_neutralize_insert_many():
    n = neutralize(Action.INSERT_MANY, {"inserted_count": 3, "inserted_ids": []})
    assert n["affected"] == 3


def test_neutralize_update():
    n = neutralize(Action.UPDATE_MANY, {"matched": 5, "modified": 4})
    assert n["affected"] == 4


def test_neutralize_delete():
    n = neutralize(Action.DELETE_ONE, {"deleted": 2})
    assert n["affected"] == 2


def test_neutralize_aggregate():
    n = neutralize(Action.AGGREGATE, [{"x": 1}, {"x": 2}])
    assert n["rows"] == [{"x": 1}, {"x": 2}]


@pytest.mark.asyncio
async def test_mongo_find_result_exposes_neutral(pipeline):
    await pipeline._executor.execute("customers", Action.INSERT_ONE, {"document": {"name": "neo"}})
    result = await pipeline.run("test-agent", "customers", Action.FIND, {})
    assert result["status"] == "success"
    # Native Mongo shape preserved.
    assert "documents" in result["data"]
    # Neutral accessors present alongside.
    assert "neutral" in result
    assert result["neutral"]["rows"] == result["data"]["documents"]
    assert "scalar" in result["neutral"]
    assert result["neutral"]["affected"] is None

    # And it survives the envelope mapping into meta.
    envelope = json.loads(from_pipeline_result(result))
    assert envelope["ok"] is True
    assert envelope["meta"]["neutral"]["rows"] == result["data"]["documents"]


@pytest.mark.asyncio
async def test_mongo_count_result_exposes_scalar(pipeline):
    await pipeline._executor.execute(
        "customers", Action.INSERT_ONE, {"document": {"name": "trinity"}}
    )
    result = await pipeline.run("test-agent", "customers", Action.COUNT, {})
    assert result["status"] == "success"
    assert result["neutral"]["scalar"] == result["data"]
    assert result["neutral"]["rows"] == []
