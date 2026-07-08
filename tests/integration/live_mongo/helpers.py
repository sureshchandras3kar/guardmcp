"""Shared MCP-tool-layer helpers for Section B/C (driving real registered
tools, not calling GuardPipeline directly like Section A)."""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from guardmcp.server import tools as tools_mod
from guardmcp.server.tools._common import ToolContext


class ConfirmingContext:
    """Elicit stub that always accepts — drives the approval confirm branch."""

    async def elicit(self, *, message, schema):
        class _R:
            action = "accept"

            class data:
                confirmed = True

        return _R()


class DecliningContext:
    """Elicit stub that always declines."""

    async def elicit(self, *, message, schema):
        class _R:
            action = "cancel"
            data = None

        return _R()


def make_mcp(pipeline, agent: str = "claude", settings=None) -> FastMCP:
    mcp = FastMCP("live")
    ctx = ToolContext(
        get_pipeline=lambda: pipeline,
        get_agent=lambda: agent,
        get_settings=lambda: settings,
    )
    tools_mod.meta.register(mcp, ctx)
    tools_mod.read.register(mcp, ctx)
    tools_mod.write.register(mcp, ctx)
    tools_mod.export.register(mcp, ctx)
    return mcp


async def call(mcp: FastMCP, name: str, **kwargs) -> dict:
    """Call a read tool (no ctx) OR a write tool (needs ctx) uniformly: try
    without ctx first (read tools), fall back to a ConfirmingContext (write
    tools always take ctx as their first positional arg, whether or not
    approval actually triggers — unused when it doesn't)."""
    tool = mcp._tool_manager.get_tool(name)
    try:
        return json.loads(await tool.fn(**kwargs))
    except TypeError as exc:
        if "missing 1 required positional argument: 'ctx'" not in str(exc):
            raise
        return json.loads(await tool.fn(ConfirmingContext(), **kwargs))
