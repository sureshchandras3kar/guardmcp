"""
MCP tool definitions — capability-neutral db_* tools with mongodb_* aliases.

Design overhaul (10 points):
 1. Capability-neutral `db_*` names + `mongodb_*` aliases (same handler).
 2. Standard error taxonomy (responses.ErrorCode).
 3. guardmcp_plan — dry-run preview of authorization/risk/affected docs.
 4. guardmcp_capabilities — discovery of backend + per-collection permitted actions.
 5. One response envelope (responses.ok/err/from_pipeline_result).
 6. Tool annotations (readOnlyHint/destructiveHint/idempotentHint) where SDK supports.
 7. Tighter input types (Literal mode, dict-shaped index keys, Field examples).
 8. Structured description template per tool.
 9. UNSUPPORTED_CAPABILITY check against active connection's plugin.supported.
10. server_version / protocol_version / backend info in guardmcp_status.

This package splits the former monolithic ``tools.py`` into focused modules:
  - ``_common``   — shared params, envelopes, guards, confirmation, ToolContext.
  - ``_registry`` — the dual-name (db_* + mongodb_*) registration helper.
  - ``meta``      — guardmcp_status / setup / capabilities / plan.
  - ``read``      — find/count/aggregate/explain/schema/indexes/list/switch.
  - ``write``     — insert/update/delete/create_index/drop_index.

Tools that touch a database are registered TWICE (db_* + mongodb_* alias) by the
shared ``register_dual`` helper; the handler is defined once. ``register_tools``
keeps its original signature so callers in __main__ are unchanged.
"""

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from mcp.server.fastmcp import FastMCP

from . import export, meta, read, write
from ._common import (
    ANNOTATIONS_SUPPORTED,
    ToolContext,
    _active_backend_info,
    _active_supported_caps,
    _annot,
    _capability_check,
    _elicit_confirm,
    _run_with_confirm,
    _validation_guard,
)

if TYPE_CHECKING:
    from ...core.pipeline import GuardPipeline

# Re-exported for callers/tests that referenced these on the old module.
__all__ = [
    "ANNOTATIONS_SUPPORTED",
    "register_tools",
    "_active_backend_info",
    "_active_supported_caps",
    "_annot",
    "_capability_check",
    "_elicit_confirm",
    "_run_with_confirm",
    "_validation_guard",
]


def register_tools(
    mcp: FastMCP,
    get_pipeline: "Callable[[], GuardPipeline]",
    get_agent: "Callable[[], str]",
    get_settings: "Callable[[], Any]" = lambda: None,
    get_active_database: "Callable[[], str | None]" = lambda: None,
    set_active_database: "Callable[[str | None], None]" = lambda _v: None,
) -> None:
    """Register all GuardMCP tools onto `mcp`. Same signature as before."""
    ctx = ToolContext(
        get_pipeline=get_pipeline,
        get_agent=get_agent,
        get_settings=get_settings,
        get_active_database=get_active_database,
        set_active_database=set_active_database,
    )
    meta.register(mcp, ctx)
    read.register(mcp, ctx)
    write.register(mcp, ctx)
    export.register(mcp, ctx)
