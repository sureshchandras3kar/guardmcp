"""Regression: `mcp.server.fastmcp.exceptions.ToolError` raised by the
mongodb/guard.py validators (banned aggregation operator, malformed pipeline
shape) used to bypass `_validation_guard`, which only caught
GuardValidationError/ValueError/GuardError — so it surfaced as a raw
uncaught FastMCP-level error instead of this codebase's own structured
`{ok:false, error:{code:"VALIDATION",...}}` envelope, unlike every other
validation failure. Found while building the live-MongoDB verification suite.
"""

import json

import pytest
from mcp.server.fastmcp import FastMCP

from guardmcp.server import tools as tools_mod


class _Executor:
    async def referenced_collections(self, params):
        return set()

    async def masked_field_references(self, params, mask_fields):
        return set()


class _Pipeline:
    _registry = None

    def _guard_aggregation(self, request, policy):
        return None

    def evaluate(self, agent, collection, action, params, database=None):
        raise AssertionError("must never reach evaluate() — validation fails first")


def _register():
    mcp = FastMCP("t")
    tools_mod.register_tools(mcp, lambda: _Pipeline(), lambda: "claude", lambda: None)
    return mcp


async def _call(mcp, name, **kw):
    tool = mcp._tool_manager.get_tool(name)
    return json.loads(await tool.fn(**kw))


@pytest.mark.asyncio
async def test_aggregate_banned_operator_returns_validation_envelope():
    mcp = _register()
    out = await _call(
        mcp, "db_aggregate", collection="users",
        pipeline_stages=[{"$match": {"$where": "this.x"}}],
    )
    assert out["ok"] is False
    assert out["error"]["code"] == "VALIDATION"


@pytest.mark.asyncio
async def test_aggregate_disallowed_stage_returns_validation_envelope():
    mcp = _register()
    out = await _call(
        mcp, "db_aggregate", collection="users",
        pipeline_stages=[{"$out": "evil"}],
    )
    assert out["ok"] is False
    assert out["error"]["code"] == "VALIDATION"


@pytest.mark.asyncio
async def test_aggregate_db_wrong_first_stage_returns_validation_envelope():
    mcp = _register()
    out = await _call(
        mcp, "db_aggregate_db", pipeline_stages=[{"$match": {}}],
    )
    assert out["ok"] is False
    assert out["error"]["code"] == "VALIDATION"


@pytest.mark.asyncio
async def test_find_dangerous_filter_returns_validation_envelope():
    mcp = _register()
    out = await _call(
        mcp, "db_find", collection="users", filter={"$where": "this.x"},
    )
    assert out["ok"] is False
    assert out["error"]["code"] == "VALIDATION"
