"""
Single registration helper encapsulating the repeated boilerplate.

Database tools are registered TWICE — once under the capability-neutral ``db_X``
name and once under the legacy ``mongodb_X`` alias — sharing one handler. The
alias gets an "(alias of ...)" description suffix. This is the ONE place that
knows how to register a dual-named tool, used by every read/write module.

Meta tools (single-named) register directly via ``mcp.tool`` and are not handled
here.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP


def register_dual(
    mcp: FastMCP,
    primary: str,
    alias: str,
    description: str,
    annotations,
    handler,
) -> None:
    """Register `handler` under both the neutral primary and legacy alias names.

    The handler is expected to already be wrapped in the validation guard (so the
    same wrapped callable is shared by both names, exactly as before).
    """
    mcp.tool(name=primary, description=description, annotations=annotations)(handler)
    alias_desc = f"{description}\n\n(alias of {primary})"
    mcp.tool(name=alias, description=alias_desc, annotations=annotations)(handler)
