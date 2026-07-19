"""db_aggregate_db — new Action.AGGREGATE_DB. This is DB-LEVEL aggregation
($currentOp/$changeStream/$documents/$listLocalSessions/$queryStats), NOT
collection data — MongoDB's db.aggregate() only accepts these as the first
stage (verified against mongodb-mcp-server's aggregateDB.ts /
DB_AGGREGATE_STAGE_OPERATORS).

mongomock-motor doesn't implement db-level aggregate stages like real MongoDB
does (no $currentOp/$changeStream simulation), so the executor's actual
document-shaping and the $changeStream bounded-timeout behavior are tested
with a fake cursor — same precedent as collStats in
test_collection_storage_size.py.
"""

import asyncio

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from guardmcp.plugins.mongodb.executor import MongoExecutor
from guardmcp.plugins.mongodb.guard import validate_db_pipeline_stages

# ── Guard: validate_db_pipeline_stages ──────────────────────────────────────


def test_current_op_is_allowed_as_first_stage():
    validate_db_pipeline_stages([{"$currentOp": {}}])  # must not raise


def test_change_stream_is_allowed_as_first_stage():
    validate_db_pipeline_stages([{"$changeStream": {}}])


def test_arbitrary_first_stage_rejected():
    with pytest.raises(ToolError, match="db-level aggregation stage"):
        validate_db_pipeline_stages([{"$match": {"status": "active"}}])


def test_empty_pipeline_rejected():
    with pytest.raises(ToolError):
        validate_db_pipeline_stages([])


def test_banned_operator_rejected_even_as_later_stage():
    with pytest.raises(ToolError, match="disallowed operator"):
        validate_db_pipeline_stages(
            [{"$currentOp": {}}, {"$match": {"$where": "this.x"}}]
        )


def test_out_stage_rejected():
    with pytest.raises(ToolError):
        validate_db_pipeline_stages([{"$currentOp": {}}, {"$out": "evil"}])


def test_non_first_normal_stage_allowed_after_current_op():
    # $currentOp emits documents that can be filtered/projected downstream —
    # only the FIRST stage is restricted to the db-level operator set.
    validate_db_pipeline_stages([{"$currentOp": {}}, {"$match": {"active": True}}])


# ── Executor: fake cursor (mongomock can't simulate $currentOp/$changeStream) ─


class _FakeCursor:
    def __init__(self, docs=None, hang=False):
        self._docs = docs or []
        self._hang = hang

    async def to_list(self, length=None):
        if self._hang:
            await asyncio.sleep(10)  # never resolves within the test timeout
        return self._docs


class _FakeDb:
    def __init__(self, cursor):
        self._cursor = cursor

    def aggregate(self, pipeline):
        return self._cursor


class _FakeClient:
    def __init__(self, cursor):
        self._cursor = cursor
        self.requested_databases: list[str | None] = []

    def get_db(self, database=None):
        self.requested_databases.append(database)
        return _FakeDb(self._cursor)


@pytest.mark.asyncio
async def test_normal_stage_returns_documents():
    executor = MongoExecutor(_FakeClient(_FakeCursor(docs=[{"opid": 1}, {"opid": 2}])))
    out = await executor._exec_aggregate_db({"pipeline": [{"$currentOp": {}}]})
    assert out == {"documents": [{"opid": 1}, {"opid": 2}], "truncated_by_size": False}


@pytest.mark.asyncio
async def test_change_stream_bounded_timeout_returns_empty_on_hang():
    executor = MongoExecutor(
        _FakeClient(_FakeCursor(hang=True)), change_stream_timeout=0.05
    )
    out = await executor._exec_aggregate_db({"pipeline": [{"$changeStream": {}}]})
    assert out == {"documents": [], "truncated_by_size": False}  # never blocks indefinitely


@pytest.mark.asyncio
async def test_change_stream_returns_events_when_available_quickly():
    executor = MongoExecutor(
        _FakeClient(_FakeCursor(docs=[{"op": "insert"}])), change_stream_timeout=0.05
    )
    out = await executor._exec_aggregate_db({"pipeline": [{"$changeStream": {}}]})
    assert out == {"documents": [{"op": "insert"}], "truncated_by_size": False}


@pytest.mark.asyncio
async def test_large_documents_capped_by_byte_budget():
    big_docs = [{"opid": i, "blob": "x" * 500_000} for i in range(5)]
    executor = MongoExecutor(_FakeClient(_FakeCursor(docs=big_docs)))
    out = await executor._exec_aggregate_db({"pipeline": [{"$currentOp": {}}]})
    assert out["truncated_by_size"] is True
    assert len(out["documents"]) < 5


# ── Regression: $currentOp/$listLocalSessions MUST target the admin db ──────
# MongoDB rejects these elsewhere ("$currentOp must be run against the
# 'admin' database") — untested before since mongomock never enforced this;
# found running the live-MongoDB verification suite against a real server.


@pytest.mark.asyncio
async def test_current_op_routes_to_admin_database_regardless_of_request_target():
    client = _FakeClient(_FakeCursor(docs=[]))
    executor = MongoExecutor(client)
    await executor._exec_aggregate_db(
        {"pipeline": [{"$currentOp": {}}]}, database="some_other_db"
    )
    assert client.requested_databases == ["admin"]


@pytest.mark.asyncio
async def test_list_local_sessions_routes_to_admin_database():
    client = _FakeClient(_FakeCursor(docs=[]))
    executor = MongoExecutor(client)
    await executor._exec_aggregate_db(
        {"pipeline": [{"$listLocalSessions": {}}]}, database="some_other_db"
    )
    assert client.requested_databases == ["admin"]


@pytest.mark.asyncio
async def test_documents_stage_still_routes_to_the_requested_database():
    client = _FakeClient(_FakeCursor(docs=[{"x": 1}]))
    executor = MongoExecutor(client)
    await executor._exec_aggregate_db(
        {"pipeline": [{"$documents": [{"x": 1}]}]}, database="some_other_db"
    )
    assert client.requested_databases == ["some_other_db"]
