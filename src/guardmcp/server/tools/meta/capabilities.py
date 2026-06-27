"""guardmcp_capabilities — backend + per-collection permitted-action discovery."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ....core.interfaces.capability import ACTION_TO_CAPABILITY
from ....core.models.domain import WRITE_ACTIONS, Action
from .._common import (
    Any,
    ToolContext,
    _active_backend_info,
    _active_supported_caps,
    ok,
)


def register(mcp: FastMCP, ctx: ToolContext) -> None:
    get_pipeline = ctx.get_pipeline
    get_agent = ctx.get_agent
    _RO = ctx.RO

    @mcp.tool(
        description=(
            "Discover what THIS agent may do: backend, supported capabilities, and "
            "per-collection permitted actions.\n"
            "Use when: before any operation, to avoid trial-and-error on permissions.\n"
            "Do NOT use when: you only need connection status — call guardmcp_status.\n"
            "Side effects: none (read-only, cheap).\n"
            "Example: guardmcp_capabilities()"
        ),
        annotations=_RO,
    )
    async def guardmcp_capabilities() -> str:
        pipeline = get_pipeline()
        agent = get_agent()
        policy = pipeline._policies.get(agent)

        backend_name, _ = _active_backend_info(pipeline)
        supported_caps = _active_supported_caps(pipeline)
        supported_values = sorted(c.value for c in supported_caps)

        if policy is None:
            return ok(
                {
                    "backend": backend_name,
                    "supported_capabilities": supported_values,
                    "agent": agent,
                    "mode": None,
                    "collections": {},
                    "masked_fields": [],
                    "connections_allow": [],
                    "note": "no policy configured — run guardmcp_setup",
                }
            )

        # Base action set per mode.
        read_actions = {
            Action.FIND,
            Action.COUNT,
            Action.AGGREGATE,
            Action.EXPLAIN,
            Action.COLLECTION_SCHEMA,
            Action.COLLECTION_INDEXES,
            Action.LIST_DATABASES,
            Action.DB_STATS,
        }
        base_actions = set(read_actions)
        if policy.mode == "readwrite":
            base_actions |= set(WRITE_ACTIONS)

        allow_actions = set(policy.actions.allow)
        deny_actions = set(policy.actions.deny)

        def _permitted_actions() -> list[Action]:
            result = []
            for act in sorted(base_actions, key=lambda a: a.value):
                if allow_actions and act.value not in allow_actions:
                    continue
                if act.value in deny_actions:
                    continue
                cap = ACTION_TO_CAPABILITY.get(act)
                if cap is not None and supported_caps and cap not in supported_caps:
                    continue
                result.append(act)
            return result

        permitted = _permitted_actions()

        def _action_entry(act: Action) -> dict[str, Any]:
            cap = ACTION_TO_CAPABILITY.get(act)
            return {"action": act.value, "capability": cap.value if cap else None}

        # Determine target collections.
        executor = pipeline._get_executor()
        try:
            known_cols = await executor.list_collections()
        except Exception:
            known_cols = []

        allow_cols = policy.collections.allow
        deny_cols = set(policy.collections.deny)
        if "*" in allow_cols:
            # Wildcard ⇒ enumerate all known collections (minus deny).
            target_cols = [c for c in known_cols if c not in deny_cols]
        elif allow_cols:
            target_cols = [c for c in allow_cols if c not in deny_cols]
        else:
            # AD-1: empty allow = deny-all ⇒ no collections are accessible.
            target_cols = []

        collections_map: dict[str, list[dict[str, Any]]] = {}
        for col in target_cols:
            collections_map[col] = [_action_entry(a) for a in permitted]

        return ok(
            {
                "backend": backend_name,
                "supported_capabilities": supported_values,
                "agent": agent,
                "mode": policy.mode,
                "collections": collections_map,
                "masked_fields": policy.mask_fields,
                "connections_allow": policy.connections_allow,
            }
        )
