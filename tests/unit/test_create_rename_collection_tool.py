"""db_create_collection / db_rename_collection — new Action.CREATE_COLLECTION /
Action.RENAME_COLLECTION, wired end to end (risk/capability/executor/tool).
Real MongoExecutor + mongomock-motor, no fakes.
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
    return pipeline, real


def _get_tool(pipeline, name):
    mcp = FastMCP("test")
    tools_mod.register_tools(mcp, lambda: pipeline, lambda: "test-agent", lambda: None)
    return mcp._tool_manager.get_tool(name)


class _FakeContext:
    async def elicit(self, *, message, schema):
        class _R:
            action = "cancel"
            data = None

        return _R()


async def _call(tool, **kwargs):
    return json.loads(await tool.fn(ctx=_FakeContext(), **kwargs))


_ALLOW_BOTH = """
agent: test-agent
mode: readwrite
collections:
  allow:
    - events
    - old_name
actions:
  allow:
    - create_collection
    - rename_collection
"""


# ── create_collection ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_collection_creates_it(tmp_path):
    pipeline, real = await _pipeline(tmp_path, _ALLOW_BOTH)
    assert "events" not in await real["testdb"].list_collection_names()

    tool = _get_tool(pipeline, "db_create_collection")
    out = await _call(tool, collection="events")

    assert out["ok"] is True
    assert "events" in await real["testdb"].list_collection_names()


@pytest.mark.asyncio
async def test_create_collection_blocked_in_readonly_mode(tmp_path):
    pipeline, real = await _pipeline(
        tmp_path,
        """
agent: test-agent
mode: readonly
collections:
  allow: [events]
""",
    )
    tool = _get_tool(pipeline, "db_create_collection")
    out = await _call(tool, collection="events")

    assert out["ok"] is False
    assert "events" not in await real["testdb"].list_collection_names()


# ── rename_collection ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rename_collection_renames_it(tmp_path):
    pipeline, real = await _pipeline(tmp_path, _ALLOW_BOTH)
    await real["testdb"]["old_name"].insert_one({"x": 1})

    tool = _get_tool(pipeline, "db_rename_collection")
    out = await _call(tool, collection="old_name", new_name="new_name")

    assert out["ok"] is True
    names = await real["testdb"].list_collection_names()
    assert "new_name" in names and "old_name" not in names


@pytest.mark.asyncio
async def test_rename_collection_blocked_in_readonly_mode(tmp_path):
    pipeline, real = await _pipeline(
        tmp_path,
        """
agent: test-agent
mode: readonly
collections:
  allow: [old_name]
""",
    )
    await real["testdb"]["old_name"].insert_one({"x": 1})
    tool = _get_tool(pipeline, "db_rename_collection")
    out = await _call(tool, collection="old_name", new_name="new_name")

    assert out["ok"] is False
    names = await real["testdb"].list_collection_names()
    assert "old_name" in names and "new_name" not in names
