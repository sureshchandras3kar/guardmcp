"""db_collection_storage_size — new Action.COLLECTION_STORAGE_SIZE.

mongomock-motor does not implement the `collStats` command (NotImplementedError
even with the dict-form call), so the ALLOWED/executes-successfully path is
tested at the executor level with a fake client (mirrors how other
`.command()`-based executor methods are tested in this codebase — there's no
existing mongomock-backed test for `explain`/`collStats`-shaped commands
either). The DENIED path (policy blocks the collection) never reaches the
executor, so that's tested end-to-end with real mongomock.
"""

import json

import pytest
from mcp.server.fastmcp import FastMCP
from mongomock_motor import AsyncMongoMockClient

from guardmcp.core.approval.store import ApprovalStore
from guardmcp.core.audit.logger import AuditLogger
from guardmcp.core.pipeline import GuardPipeline
from guardmcp.core.policy.engine import PolicyEngine
from guardmcp.core.policy.loader import PolicyLoader
from guardmcp.core.risk.engine import RiskEngine
from guardmcp.plugins.mongodb.executor import MongoExecutor
from guardmcp.server import tools as tools_mod

# ── Executor-level: real field extraction from a fake collStats response ─────


class _FakeDb:
    def __init__(self, stats: dict):
        self._stats = stats

    async def command(self, cmd, arg=None):
        assert cmd == "collStats"
        return self._stats


class _FakeClient:
    def __init__(self, stats: dict):
        self._stats = stats

    def get_db(self, database=None):
        return _FakeDb(self._stats)


@pytest.mark.asyncio
async def test_exec_collection_storage_size_extracts_fields():
    stats = {
        "size": 1024, "storageSize": 2048, "count": 10,
        "avgObjSize": 102, "totalIndexSize": 512, "ns": "testdb.users",
    }
    executor = MongoExecutor(_FakeClient(stats))
    out = await executor._exec_collection_storage_size("users", database="testdb")
    assert out == {
        "size": 1024, "storage_size": 2048, "count": 10,
        "avg_obj_size": 102, "total_index_size": 512,
    }


@pytest.mark.asyncio
async def test_exec_collection_storage_size_missing_fields_are_none():
    executor = MongoExecutor(_FakeClient({}))
    out = await executor._exec_collection_storage_size("empty_col")
    assert out == {
        "size": None, "storage_size": None, "count": None,
        "avg_obj_size": None, "total_index_size": None,
    }


# ── Tool-level: dual registration + policy-denied path (real mongomock) ─────


def _make_client():
    real = AsyncMongoMockClient()

    class _Client:
        def get_collection(self, name, database=None):
            return real["testdb"][name]

        def get_db(self, database=None):
            return real["testdb"]

        async def list_collection_names(self, database=None):
            return await real["testdb"].list_collection_names()

        async def list_databases(self):  # noqa: RUF029
            return [{"name": "testdb", "sizeOnDisk": 0}]

        def close(self):
            pass

    return _Client(), real


async def _pipeline(tmp_path, policy_yaml: str):
    pol = tmp_path / "policy.yaml"
    pol.write_text(policy_yaml)
    loader = PolicyLoader(pol)
    loader.load()
    client, real = _make_client()
    pipeline = GuardPipeline(
        policy_loader=loader,
        policy_engine=PolicyEngine(),
        risk_engine=RiskEngine(),
        audit_logger=AuditLogger(tmp_path / "audit.jsonl"),
        approval_store=ApprovalStore(timeout_seconds=1.0),
        executor=MongoExecutor(client),
    )
    return pipeline


def _get_tool(pipeline, name):
    mcp = FastMCP("test")
    tools_mod.register_tools(mcp, lambda: pipeline, lambda: "test-agent", lambda: None)
    return mcp._tool_manager.get_tool(name)


async def _call(tool, **kwargs):
    return json.loads(await tool.fn(**kwargs))


@pytest.mark.asyncio
async def test_denied_for_disallowed_collection(tmp_path):
    pipeline = await _pipeline(
        tmp_path,
        """
agent: test-agent
mode: readonly
collections:
  allow: [users]
""",
    )
    tool = _get_tool(pipeline, "db_collection_storage_size")
    out = await _call(tool, collection="not_allowed")
    assert out["ok"] is False


@pytest.mark.asyncio
async def test_allowed_in_readonly_mode():
    # COLLECTION_STORAGE_SIZE is read-only (not in WRITE_ACTIONS) -> readonly
    # mode must NOT block it, unlike a write/DDL action.
    from guardmcp.core.models.domain import WRITE_ACTIONS, Action

    assert Action.COLLECTION_STORAGE_SIZE not in WRITE_ACTIONS
