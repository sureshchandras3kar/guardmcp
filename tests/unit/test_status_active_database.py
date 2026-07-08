"""guardmcp_status — regression for a real bug found reviewing the
new-connection use case: after switching to a non-default named connection
(a different database), the status report's `database` field still showed
the DEFAULT connection's configured database (a single global Settings
field), even though `connection`/`collection_count`/`db_size` above it were
already correctly computed against the REAL active connection. Internally
inconsistent and just wrong the moment an agent uses more than one connection.
"""

import json

import pytest
from mcp.server.fastmcp import FastMCP

from guardmcp.core.approval.store import ApprovalStore
from guardmcp.core.audit.logger import AuditLogger
from guardmcp.core.pipeline import GuardPipeline
from guardmcp.core.policy.engine import PolicyEngine
from guardmcp.core.policy.loader import PolicyLoader
from guardmcp.core.registry.connections import ConnectionEntry, ConnectionRegistry, reset_active
from guardmcp.core.risk.engine import RiskEngine
from guardmcp.server.tools._common import ToolContext
from guardmcp.server.tools.meta import status as status_tool


class _FakeExecutor:
    def __init__(self, database: str):
        self._database = database

    async def list_collections(self, database=None):
        return []

    async def db_stats(self):
        return {"storageSize": 0}


class _Settings:
    # The DEFAULT connection's configured database — a single global field,
    # which is exactly what the bug incorrectly used for EVERY connection.
    mongodb_database = "default_db"
    rate_limit_rps = 0
    protocol_version = None


@pytest.fixture(autouse=True)
def _reset():
    reset_active()
    yield
    reset_active()


def _pipeline_with_two_connections(tmp_path):
    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text("agent: claude\nmode: readonly\ncollections:\n  allow: ['*']\n")
    loader = PolicyLoader(policy_path)
    loader.load()

    registry = ConnectionRegistry()
    registry._registry["default"] = ConnectionEntry(
        client=None, database="default_db", executor=_FakeExecutor("default_db"),
    )
    registry._registry["analytics"] = ConnectionEntry(
        client=None, database="analytics_db", executor=_FakeExecutor("analytics_db"),
    )

    pipeline = GuardPipeline(
        policy_loader=loader,
        policy_engine=PolicyEngine(),
        risk_engine=RiskEngine(),
        audit_logger=AuditLogger(tmp_path / "audit.jsonl"),
        approval_store=ApprovalStore(timeout_seconds=1.0),
        executor=_FakeExecutor("default_db"),
        registry=registry,
    )
    return pipeline, registry


def _get_status_tool(pipeline):
    mcp = FastMCP("test")
    ctx = ToolContext(
        get_pipeline=lambda: pipeline, get_agent=lambda: "claude",
        get_settings=lambda: _Settings(),
    )
    status_tool.register(mcp, ctx)
    return mcp._tool_manager.get_tool("guardmcp_status")


@pytest.mark.asyncio
async def test_status_database_matches_active_connection_after_switch(tmp_path):
    pipeline, registry = _pipeline_with_two_connections(tmp_path)
    assert pipeline.switch_connection("analytics") is True
    assert pipeline.active_connection() == "analytics"

    tool = _get_status_tool(pipeline)
    payload = json.loads(await tool.fn())
    stats = payload["data"]["stats"]

    assert stats["connection"] == "analytics"
    # The bug: this used to be "default_db" (settings.mongodb_database)
    # regardless of which connection was actually active.
    assert stats["database"] == "analytics_db"


@pytest.mark.asyncio
async def test_status_database_matches_default_when_not_switched(tmp_path):
    pipeline, _registry = _pipeline_with_two_connections(tmp_path)
    tool = _get_status_tool(pipeline)
    payload = json.loads(await tool.fn())
    stats = payload["data"]["stats"]
    assert stats["connection"] == "default"
    assert stats["database"] == "default_db"
