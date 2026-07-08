"""db_logs / mongodb_logs — new Action.MONGODB_LOGS (admin `getLog` command).
Log lines are opaque strings, not documents, so masking doesn't apply
(Action.MONGODB_LOGS is in NO_MASK_ACTIONS). mongomock-motor has no admin
command simulation, so the executor is tested with a fake client, matching
the collStats/aggregate_db precedent.
"""

import pytest

from guardmcp.plugins.mongodb.executor import MongoExecutor


class _FakeClient:
    def __init__(self, result: dict):
        self._result = result
        self.requested_log_type = None

    async def get_log(self, log_type="global"):
        self.requested_log_type = log_type
        return self._result


@pytest.mark.asyncio
async def test_mongodb_logs_returns_lines_and_total():
    client = _FakeClient({"totalLinesWritten": 3, "log": ["a", "b", "c"]})
    executor = MongoExecutor(client)
    out = await executor._exec_mongodb_logs({})
    assert out == {
        "log_type": "global", "total_lines_written": 3,
        "lines": ["a", "b", "c"], "truncated_by_size": False,
    }
    assert client.requested_log_type == "global"


@pytest.mark.asyncio
async def test_mongodb_logs_respects_log_type_param():
    client = _FakeClient({"totalLinesWritten": 1, "log": ["startup warning"]})
    executor = MongoExecutor(client)
    out = await executor._exec_mongodb_logs({"log_type": "startupWarnings"})
    assert client.requested_log_type == "startupWarnings"
    assert out["lines"] == ["startup warning"]


@pytest.mark.asyncio
async def test_mongodb_logs_capped_to_max_limit():
    lines = [f"line{i}" for i in range(10)]
    client = _FakeClient({"totalLinesWritten": 10, "log": lines})
    executor = MongoExecutor(client, max_limit=3)
    out = await executor._exec_mongodb_logs({})
    # Capped to the LAST 3 lines (most recent), total_lines_written unaffected.
    assert out["lines"] == ["line7", "line8", "line9"]
    assert out["total_lines_written"] == 10


@pytest.mark.asyncio
async def test_mongodb_logs_missing_log_key_defaults_empty():
    client = _FakeClient({})
    executor = MongoExecutor(client)
    out = await executor._exec_mongodb_logs({})
    assert out == {
        "log_type": "global", "total_lines_written": 0,
        "lines": [], "truncated_by_size": False,
    }


@pytest.mark.asyncio
async def test_mongodb_logs_shortens_a_very_long_line():
    client = _FakeClient({"totalLinesWritten": 1, "log": ["x" * 10_000]})
    executor = MongoExecutor(client)
    out = await executor._exec_mongodb_logs({})
    assert out["truncated_by_size"] is True
    assert len(out["lines"][0]) < 10_000
    assert out["lines"][0].endswith("...[truncated]")
