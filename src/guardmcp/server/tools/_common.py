"""
Shared building blocks for the GuardMCP tool modules.

Everything the per-area tool modules (meta / read / write) need in common lives
here ONCE: the parameter type aliases, the response-envelope helpers, the
validation guard, the capability check, in-band confirmation, and the backend
introspection helpers. A :class:`ToolContext` bundles the three getter callables
(get_pipeline / get_agent / get_settings) plus the prebuilt ToolAnnotations so a
module's ``register(mcp, ctx)`` has everything it needs.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Any, Literal

from mcp.server.fastmcp import Context
from pydantic import BaseModel, Field

from ...core.interfaces.capability import ACTION_TO_CAPABILITY, Capability
from ...core.interfaces.errors import GuardError, GuardValidationError
from ...core.models.domain import Action
from ...core.validation import JsonDict, JsonList, SafeLimit
from ..responses import ErrorCode, err, from_pipeline_result, ok

if TYPE_CHECKING:
    from ...core.pipeline import GuardPipeline

try:  # pragma: no cover - import guard
    from mcp.types import ToolAnnotations

    _ANNOTATIONS_SUPPORTED = True
except Exception:  # pragma: no cover
    ToolAnnotations = None  # type: ignore[assignment,misc]
    _ANNOTATIONS_SUPPORTED = False

# Exposed so tests / smoke checks can report whether annotations were applied.
ANNOTATIONS_SUPPORTED = _ANNOTATIONS_SUPPORTED

# Re-export commonly used names so tool modules import from one place.
__all__ = [
    "ANNOTATIONS_SUPPORTED",
    "Action",
    "Annotated",
    "Any",
    "BaseModel",
    "Capability",
    "Context",
    "DocumentParam",
    "ErrorCode",
    "Field",
    "FilterParam",
    "JsonDict",
    "JsonList",
    "Literal",
    "ProjectionParam",
    "SafeLimit",
    "SafeSkip",
    "SortParam",
    "ToolContext",
    "UpdateParam",
    "_annot",
    "_capability_check",
    "_elicit_confirm",
    "_resolve_database",
    "_run_with_confirm",
    "_validation_guard",
    "err",
    "from_pipeline_result",
    "ok",
]

# ── Parameter type aliases (point 7) ────────────────────────────────────────────

# Pagination skip — non-negative integer
SafeSkip = Annotated[int, Field(ge=0, description="Documents to skip (for pagination).")]

FilterParam = Annotated[
    JsonDict,
    Field(
        description="Query filter as plain JSON. No $where/$function.",
        examples=[{"status": "active"}],
    ),
]
SortParam = Annotated[
    JsonDict,
    Field(description="Sort spec, field -> 1 (asc) or -1 (desc).", examples=[{"created_at": -1}]),
]
ProjectionParam = Annotated[
    JsonDict,
    Field(description="Fields to include/exclude.", examples=[{"name": 1, "_id": 0}]),
]
DocumentParam = Annotated[
    JsonDict,
    Field(description="Document to write.", examples=[{"name": "Ada", "status": "active"}]),
]
UpdateParam = Annotated[
    JsonDict,
    Field(
        description='Update spec, e.g. {"$set": {...}}.',
        examples=[{"$set": {"status": "inactive"}}],
    ),
]


# ── In-band confirmation schema ────────────────────────────────────────────────


class _ConfirmAction(BaseModel):
    confirmed: bool


async def _elicit_confirm(ctx: Context, message: str) -> bool:
    """Ask human for in-band yes/no via MCP elicitation. Returns True if confirmed."""
    try:
        result = await ctx.elicit(message=message, schema=_ConfirmAction)
        return result.action == "accept" and bool(result.data and result.data.confirmed)
    except Exception:
        # Client doesn't support elicitation — deny by default (safe)
        return False


def _annot(**kwargs: Any):
    """Build a ToolAnnotations if the SDK supports it, else None (skip gracefully)."""
    if not _ANNOTATIONS_SUPPORTED:
        return None
    return ToolAnnotations(**kwargs)


def _validation_guard(fn):
    """
    Wrap an async tool handler so validation errors return a uniform VALIDATION
    envelope. functools.wraps preserves __wrapped__ so FastMCP's inspect.signature
    introspection still sees the real parameter schema (not *args/**kwargs).
    """

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> str:
        try:
            return await fn(*args, **kwargs)
        except (GuardValidationError, ValueError) as exc:
            return err(ErrorCode.VALIDATION, str(exc), retryable=False)
        except GuardError as exc:
            return err(ErrorCode.BACKEND_ERROR, str(exc), retryable=True)

    return wrapper


def _capability_check(pipeline: GuardPipeline, action: Action) -> str | None:
    """
    Point 9: if the ACTIVE connection has a plugin, verify it supports the
    capability for `action`. Returns an err() envelope string if unsupported,
    else None. Connections without a plugin skip the check (getattr guard).
    """
    registry = getattr(pipeline, "_registry", None)
    if registry is None:
        return None
    get_active = getattr(registry, "get_active", None)
    if get_active is None:
        return None
    entry = get_active()
    plugin = getattr(entry, "plugin", None) if entry is not None else None
    supported = getattr(plugin, "supported", None) if plugin is not None else None
    if supported is None:
        return None
    capability = ACTION_TO_CAPABILITY.get(action)
    if capability is None or capability in supported:
        return None
    name = getattr(plugin, "name", "unknown")
    return err(
        ErrorCode.UNSUPPORTED_CAPABILITY,
        f"backend '{name}' does not support {capability.value}",
        retryable=False,
        suggested_action="call guardmcp_capabilities",
    )


# ── Backend introspection helpers ───────────────────────────────────────────────


def _active_plugin(pipeline: GuardPipeline):
    """Return the active connection's DatabasePlugin, or None.

    Single source of the registry→get_active→entry→plugin walk. Used by
    guardmcp_plan to request a best-effort cost estimate through the plugin
    boundary. Returns None when there is no registry / no plugin, so the
    caller degrades gracefully (UNKNOWN cost) instead of crashing.
    """
    registry = getattr(pipeline, "_registry", None)
    if registry is None:
        return None
    get_active = getattr(registry, "get_active", None)
    if get_active is None:
        return None
    entry = get_active()
    return getattr(entry, "plugin", None) if entry is not None else None


def _active_supported_caps(pipeline: GuardPipeline) -> frozenset:
    """Capabilities supported by the active connection's plugin (fallback: all)."""
    plugin = _active_plugin(pipeline)
    supported = getattr(plugin, "supported", None) if plugin is not None else None
    if supported:
        return frozenset(supported)
    return frozenset(Capability)


def _active_backend_info(pipeline: GuardPipeline) -> tuple[str, int]:
    """Return (backend_name, supported_capability_count) for the active connection."""
    plugin = _active_plugin(pipeline)
    if plugin is not None:
        name = getattr(plugin, "name", "mongodb")
        supported = getattr(plugin, "supported", None)
        count = len(supported) if supported else len(Capability)
        return name, count
    return "mongodb", len(Capability)


# ── Shared confirmation helper ─────────────────────────────────────────────────


async def _run_with_confirm(
    ctx: Context,
    pipeline: GuardPipeline,
    agent: str,
    collection: str,
    action: Action,
    params: dict[str, Any],
    database: str | None = None,
) -> str:
    from ...core.models.domain import DecisionStatus

    eval_result = pipeline.evaluate(agent, collection, action, params, database=database)
    decision = eval_result.decision

    if decision.status == DecisionStatus.DENIED:
        return from_pipeline_result({"status": "denied", "reason": decision.reason})

    if decision.status == DecisionStatus.APPROVAL_REQUIRED:
        risk_label = decision.risk.value if decision.risk else "HIGH"
        msg = (
            f"⚠️ {risk_label} risk operation requires approval.\n"
            f"Action: {action.value}\n"
            f"Collection: {collection}\n"
            f"Reason: {decision.reason}\n\n"
            "Do you confirm? (confirmed: true/false)"
        )
        confirmed = await _elicit_confirm(ctx, msg)
        if not confirmed:
            return from_pipeline_result(
                {"status": "denied", "reason": "operation declined by user."}
            )
        result = await pipeline.execute_approved(eval_result)
        return from_pipeline_result(result)

    # ALLOWED — execute using pre-computed eval (no re-evaluation)
    await pipeline._audit.log(
        pipeline._audit.build(
            agent=agent,
            collection=collection,
            action=action.value,
            status=decision.status.value,
            reason=decision.reason,
            risk=decision.risk.value if decision.risk else None,
            request_id=eval_result.request.request_id,
        )
    )
    result = await pipeline._execute_and_build(
        eval_result.request, eval_result.policy, database=database
    )
    return from_pipeline_result(result)


# ── Context bundle passed to each tool module's register() ──────────────────────


@dataclass
class ToolContext:
    """Bundles getters + prebuilt annotations shared by all tool modules."""

    get_pipeline: Callable[[], GuardPipeline]
    get_agent: Callable[[], str]
    get_settings: Callable[[], Any]
    get_active_database: Callable[[], str | None] = lambda: None
    set_active_database: Callable[[str | None], None] = lambda _v: None

    def __post_init__(self) -> None:
        self.RO = _annot(readOnlyHint=True)
        self.WRITE = _annot(readOnlyHint=False, destructiveHint=False)
        self.DESTRUCTIVE = _annot(readOnlyHint=False, destructiveHint=True)
        self.DESTRUCTIVE_IDEMPOTENT = _annot(
            readOnlyHint=False, destructiveHint=True, idempotentHint=True
        )


def _resolve_database(ctx: ToolContext, per_call: str | None) -> str | None:
    """Effective database: per-call arg → active session db → None (connection default)."""
    return per_call or ctx.get_active_database()
