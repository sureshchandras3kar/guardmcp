import json

import pytest
from mcp.server.fastmcp import FastMCP

from guardmcp.core.policy.models import CollectionPolicy, DatabaseScope, Policy
from guardmcp.server.tools import read as read_tools
from guardmcp.server.tools._common import ToolContext


class _Pipeline:
    def __init__(self, policy): self._p = policy
    _registry = None
    async def use_database_audited(self, agent, name):
        return self._p.database_permitted(name)


def _register(policy):
    mcp = FastMCP("t")
    box = {"db": None}
    ctx = ToolContext(get_pipeline=lambda: _Pipeline(policy), get_agent=lambda: "claude",
                      get_settings=lambda: None,
                      get_active_database=lambda: box["db"],
                      set_active_database=lambda v: box.__setitem__("db", v))
    read_tools.register(mcp, ctx)
    return mcp, box


async def _call(mcp, name, **kw):
    tool = mcp._tool_manager.get_tool(name)
    return json.loads(await tool.fn(**kw))


@pytest.mark.asyncio
async def test_use_database_allowed_sets_active():
    p = Policy(agent="claude", databases_allow=["db1"],
               databases={"db1": DatabaseScope(collections=CollectionPolicy(allow=["user"]))})
    mcp, box = _register(p)
    out = await _call(mcp, "mongodb_use_database", database="db1")
    assert out["ok"] is True and box["db"] == "db1"


@pytest.mark.asyncio
async def test_use_database_denied():
    p = Policy(agent="claude", databases_allow=["db1"],
               databases={"db1": DatabaseScope(collections=CollectionPolicy(allow=["user"]))})
    mcp, box = _register(p)
    out = await _call(mcp, "mongodb_use_database", database="db2")
    assert out["ok"] is False and box["db"] is None
