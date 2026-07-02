import json

import pytest
from mcp.server.fastmcp import FastMCP

from guardmcp.core.interfaces.cost import CostEstimate, CostLevel
from guardmcp.core.models.domain import Action, Decision, DecisionStatus, Request
from guardmcp.core.pipeline import EvalResult
from guardmcp.server.tools._common import ToolContext
from guardmcp.server.tools.meta import plan_query


class _Executor:
    async def collection_indexes(self, collection):
        return [{"name": "status_1", "key": [("status", 1)]}]


class _Plugin:
    name = "mongodb"

    def __init__(self):
        self._executor = _Executor()

    async def relationships(self, resources):
        return []

    async def estimate(self, req):
        return CostEstimate(estimated_cost=CostLevel.LOW)


class _Entry:
    plugin = _Plugin()


class _Registry:
    def get_active(self):
        return _Entry()


class _Pipeline:
    _registry = _Registry()

    async def discover_collections(self, agent):
        return ["user"]

    async def describe_collection(self, agent, collection):
        return {"fields": {"status": "string"}}

    def evaluate_capability(self, agent, resource, capability, request=None):
        return EvalResult(
            request=Request(agent=agent, collection=resource, action=Action.FIND, params={}),
            decision=Decision(status=DecisionStatus.ALLOWED, reason="ok"),
            policy=None,
        )


def _register():
    mcp = FastMCP("test")
    ctx = ToolContext(
        get_pipeline=lambda: _Pipeline(),
        get_agent=lambda: "claude",
        get_settings=lambda: None,
    )
    plan_query.register(mcp, ctx)
    return mcp


@pytest.mark.asyncio
async def test_plan_query_tool_returns_recommended_plan():
    mcp = _register()
    tool = mcp._tool_manager.get_tool("guardmcp_plan_query")
    out = json.loads(await tool.fn(intent="show active users"))
    assert out["ok"] is True
    assert out["data"]["recommended_plan"]["request"]["filter"] == {"status": "ACTIVE"}


@pytest.mark.asyncio
async def test_relationships_tool_returns_graph():
    mcp = _register()
    tool = mcp._tool_manager.get_tool("guardmcp_relationships")
    out = json.loads(await tool.fn())
    assert out["ok"] is True
    assert out["data"]["relationships"]["nodes"] == ["user"]
