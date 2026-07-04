"""Tests for Task 6: policy-filtered list_databases + active/allowed databases in status."""

from __future__ import annotations

import json

import pytest
from mcp.server.fastmcp import FastMCP

from guardmcp.core.policy.models import Policy
from guardmcp.server.tools import read as read_tools
from guardmcp.server.tools._common import ToolContext

# ── Minimal stubs ────────────────────────────────────────────────────────────


class _PolicyStore:
    def __init__(self, policy: Policy) -> None:
        self._p = policy

    def get(self, agent: str) -> Policy:
        return self._p


class _Pipeline:
    def __init__(self, policy: Policy, dbs: list[str]) -> None:
        self._dbs = dbs
        self._policies = _PolicyStore(policy)
        self._registry = None

    async def run(self, agent, collection, action, params, database=None):  # noqa: PLR0913
        return {
            "status": "success",
            "data": {"databases": [{"name": n} for n in self._dbs]},
        }

    def supports(self, capability) -> bool:  # noqa: ARG002
        return True

    def _get_executor(self):
        return None

    def active_connection(self):
        return "default"

    def list_connections(self):
        return ["default"]


class _Settings:
    mongodb_database = "testdb"
    rate_limit_rps = 0
    rate_limit_burst = 0
    protocol_version = "2024-11-05"


def _register(policy: Policy, dbs: list[str], active_db: str | None = "db1") -> FastMCP:
    mcp = FastMCP("t")
    ctx = ToolContext(
        get_pipeline=lambda: _Pipeline(policy, dbs),
        get_agent=lambda: "claude",
        get_settings=lambda: _Settings(),
        get_active_database=lambda: active_db,
        set_active_database=lambda v: None,
    )
    read_tools.register(mcp, ctx)
    return mcp


async def _call(mcp: FastMCP, name: str, **kw):
    return json.loads(await mcp._tool_manager.get_tool(name).fn(**kw))


# ── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_databases_filtered_to_allowed():
    """When databases_allow is non-empty, only allowed databases are returned."""
    p = Policy(agent="claude", databases_allow=["db1", "db2"])
    mcp = _register(p, ["db1", "db2", "secret_db"])
    out = await _call(mcp, "mongodb_list_databases")
    assert out["ok"] is True
    names = {d["name"] for d in out["data"]["databases"]}
    assert names == {"db1", "db2"}
    assert "secret_db" not in names


@pytest.mark.asyncio
async def test_list_databases_empty_allow_returns_all():
    """When databases_allow is empty, all databases are returned (back-compat)."""
    p = Policy(agent="claude", databases_allow=[])
    mcp = _register(p, ["db1", "db2", "secret_db"])
    out = await _call(mcp, "mongodb_list_databases")
    assert out["ok"] is True
    names = {d["name"] for d in out["data"]["databases"]}
    assert names == {"db1", "db2", "secret_db"}


@pytest.mark.asyncio
async def test_list_databases_db_alias_also_filtered():
    """The db_list_databases alias also applies the filter."""
    p = Policy(agent="claude", databases_allow=["db1"])
    mcp = _register(p, ["db1", "db2"])
    out = await _call(mcp, "db_list_databases")
    assert out["ok"] is True
    names = {d["name"] for d in out["data"]["databases"]}
    assert names == {"db1"}


# ── Status tests ─────────────────────────────────────────────────────────────


class _StatusPipeline:
    """Minimal pipeline stub for status tests (avoids executor.list_collections calls)."""

    def __init__(self, policy: Policy) -> None:
        self._policies = _PolicyStore(policy)
        self._registry = None

    def active_connection(self) -> str:
        return "default"

    def _get_executor(self):
        class _Exec:
            async def list_collections(self_):  # noqa: N805
                return ["col1"]

            async def db_stats(self_):  # noqa: N805
                return {"storageSize": 1024}

        return _Exec()

    def supports(self, capability) -> bool:  # noqa: ARG002
        return True

    def list_connections(self):
        return ["default"]


def _register_status(policy: Policy, active_db: str | None = "mydb") -> FastMCP:
    from guardmcp.server.tools.meta import status as status_mod

    mcp = FastMCP("t")
    ctx = ToolContext(
        get_pipeline=lambda: _StatusPipeline(policy),
        get_agent=lambda: "claude",
        get_settings=lambda: _Settings(),
        get_active_database=lambda: active_db,
        set_active_database=lambda v: None,
    )
    status_mod.register(mcp, ctx)
    return mcp


@pytest.mark.asyncio
async def test_status_includes_active_and_allowed_databases():
    """guardmcp_status stats payload includes active_database and allowed_databases."""
    p = Policy(agent="claude", databases_allow=["db1", "db2"])
    mcp = _register_status(p, active_db="db1")
    tool = mcp._tool_manager.get_tool("guardmcp_status")
    out = json.loads(await tool.fn())
    assert out["ok"] is True
    stats = out["data"]["stats"]
    assert stats["active_database"] == "db1"
    assert stats["allowed_databases"] == ["db1", "db2"]


@pytest.mark.asyncio
async def test_status_allowed_databases_empty_when_no_policy():
    """guardmcp_status allowed_databases is [] and active_database is None when no policy."""
    p = Policy(agent="claude", databases_allow=[])
    mcp = _register_status(p, active_db=None)
    tool = mcp._tool_manager.get_tool("guardmcp_status")
    out = json.loads(await tool.fn())
    assert out["ok"] is True
    stats = out["data"]["stats"]
    assert stats["active_database"] is None
    assert stats["allowed_databases"] == []
