"""db_drop_collection — Action.DROP/_exec_drop/risk/capability already existed
(fully wired), only the MCP tool registration was missing. Real MongoExecutor +
mongomock-motor end to end (no fakes) to prove the wiring, not just a mock call.
"""

import json

import pytest
import pytest_asyncio
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
    await real["testdb"]["staging"].insert_one({"x": 1})
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
    """Minimal FastMCP Context stub — only reached if approval elicitation
    triggers, which these tests avoid by policy (no approval.critical set)."""

    async def elicit(self, *, message, schema):
        class _R:
            action = "cancel"
            data = None

        return _R()


async def _call(tool, **kwargs):
    return json.loads(await tool.fn(ctx=_FakeContext(), **kwargs))


@pytest_asyncio.fixture
async def allowed_pipeline(tmp_path):
    # No approval.critical -> ALLOWED, no elicit confirmation needed for this test.
    return await _pipeline(
        tmp_path,
        """
agent: test-agent
mode: readwrite
collections:
  allow:
    - staging
actions:
  allow:
    - drop
""",
    )


@pytest.mark.asyncio
async def test_drop_collection_actually_drops(allowed_pipeline):
    pipeline, real = allowed_pipeline
    assert "staging" in await real["testdb"].list_collection_names()

    tool = _get_tool(pipeline, "db_drop_collection")
    out = await _call(tool, collection="staging")

    assert out["ok"] is True
    assert "staging" not in await real["testdb"].list_collection_names()


@pytest.mark.asyncio
async def test_drop_collection_blocked_in_readonly_mode(tmp_path):
    pipeline, real = await _pipeline(
        tmp_path,
        """
agent: test-agent
mode: readonly
collections:
  allow:
    - staging
""",
    )
    tool = _get_tool(pipeline, "db_drop_collection")
    out = await _call(tool, collection="staging")

    assert out["ok"] is False
    assert "staging" in await real["testdb"].list_collection_names()  # untouched


@pytest.mark.asyncio
async def test_drop_collection_denied_for_disallowed_collection(allowed_pipeline):
    pipeline, real = allowed_pipeline
    tool = _get_tool(pipeline, "db_drop_collection")
    out = await _call(tool, collection="not_allowed")

    assert out["ok"] is False
    assert "staging" in await real["testdb"].list_collection_names()
