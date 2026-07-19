import json

import pytest
from mcp.server.fastmcp import FastMCP

from guardmcp.core.policy.models import Policy
from guardmcp.server.tools._common import ToolContext
from guardmcp.server.tools.meta import plan_query


class _Plugin:
    name = "mongodb"
    _executor = None

    async def relationships(self, resources):
        return []

    async def sample_field_values(self, collection, field, database=None, cap=100):
        return {"identity": ["a", "b"], "inventory": ["b", "c"]}.get(database, [])


class _Entry:
    plugin = _Plugin()


class _Registry:
    def get_active(self):
        return _Entry()


class _Pipeline:
    _registry = _Registry()
    _policies = None

    async def discover_collections(self, agent, database=None):
        return {"identity": ["user"], "inventory": ["resource"]}.get(database, [])

    async def describe_collection(self, agent, collection, database=None):
        return {
            ("identity", "user"): {"fields": {"account_id": "string"}},
            ("inventory", "resource"): {"fields": {"account_id": "string"}},
        }.get((database, collection))


def _register(policy):
    mcp = FastMCP("t")
    pipe = _Pipeline()

    class _L:
        def get(self, a):
            return policy

    pipe._policies = _L()
    ctx = ToolContext(
        get_pipeline=lambda: pipe,
        get_agent=lambda: "claude",
        get_settings=lambda: None,
    )
    plan_query.register(mcp, ctx)
    return mcp


async def _call(mcp, name, **kw):
    return json.loads(await mcp._tool_manager.get_tool(name).fn(**kw))


@pytest.mark.asyncio
async def test_relationships_includes_cross_db_edges():
    p = Policy(agent="claude", databases_allow=["identity", "inventory"])
    out = await _call(_register(p), "guardmcp_relationships")
    edges = out["data"]["cross_db_edges"]
    assert any(
        e["from"]["field"] == "account_id"
        and {e["from"]["database"], e["to"]["database"]} == {"identity", "inventory"}
        for e in edges
    )


@pytest.mark.asyncio
async def test_no_databases_allow_gives_empty_cross_db_edges():
    p = Policy(agent="claude")  # no databases_allow
    out = await _call(_register(p), "guardmcp_relationships")
    assert out["data"]["cross_db_edges"] == []
