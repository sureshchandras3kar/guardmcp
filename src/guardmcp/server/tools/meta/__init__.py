"""
GuardMCP meta tools (single-named, no db_/mongodb_ alias).

The former monolithic ``meta.py`` is split into one module per tool group:
  - ``status``       — guardmcp_status
  - ``setup``        — guardmcp_setup (survey + YAML writer)
  - ``capabilities`` — guardmcp_capabilities
  - ``plan``         — guardmcp_plan (+ _estimate_cost helper)
  - ``explain``      — guardmcp_explain_policy + guardmcp_simulate_policy

``register`` keeps the EXACT signature meta.register was called with from
``server/tools/__init__.py`` and fans out to each module's register, preserving
tool names, descriptions, annotations, and envelope behavior.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .._common import ToolContext
from . import capabilities, explain, plan, setup, status


def register(mcp: FastMCP, ctx: ToolContext) -> None:
    """Register all meta tools onto ``mcp``."""
    status.register(mcp, ctx)
    setup.register(mcp, ctx)
    capabilities.register(mcp, ctx)
    plan.register(mcp, ctx)
    explain.register(mcp, ctx)
