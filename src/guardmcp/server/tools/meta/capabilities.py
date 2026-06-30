"""guardmcp_capabilities — backend + per-collection permitted-action discovery.

Permission derivation goes through the REAL authorization engine
(``GuardPipeline.evaluate``) — NOT a second inline allow/deny re-implementation.
For each (collection, candidate action) we ask the pipeline with empty params and
read ``EvalResult.decision.status`` + ``.risk``. This guarantees the discovery
view matches actual authorization (temporal validity, capability-supported
filtering, scope rules) with zero drift.

NOTE on risk realism: evaluate({}) yields the BASELINE/static risk for an empty
filter. Scope escalation (e.g. empty-filter mutations → CRITICAL) is reflected in
the per-action risk where applicable, so the risk shown is honest for the
zero-argument case the agent sees here.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ....core.interfaces.capability import ACTION_TO_CAPABILITY, Capability
from ....core.models.domain import WRITE_ACTIONS, Action, DecisionStatus
from .._common import (
    Any,
    ToolContext,
    _active_backend_info,
    _active_supported_caps,
    ok,
)

# Cap enumeration for wildcard/large collection lists so the tool stays cheap.
_MAX_COLLECTIONS = 200

# Read-side candidate actions (same starting set as before); WRITE_ACTIONS are
# added when the policy mode is readwrite. The DECISION still comes from
# evaluate(), never from this set.
_READ_ACTIONS: frozenset[Action] = frozenset(
    {
        Action.FIND,
        Action.COUNT,
        Action.AGGREGATE,
        Action.EXPLAIN,
        Action.COLLECTION_SCHEMA,
        Action.COLLECTION_INDEXES,
        Action.LIST_DATABASES,
        Action.DB_STATS,
    }
)


def register(mcp: FastMCP, ctx: ToolContext) -> None:
    get_pipeline = ctx.get_pipeline
    get_agent = ctx.get_agent
    get_settings = ctx.get_settings
    _RO = ctx.RO

    def _limits_block(pipeline: Any) -> dict[str, Any]:
        """Build the top-level limits object from the executor + Settings.

        max_documents prefers the active executor's configured cap (``_max_limit``)
        and falls back to Settings/the documented default (500). rate_limit is
        null when disabled (rps == 0).
        """
        settings = get_settings()

        # max_documents: prefer the live executor cap, else settings, else 500.
        max_documents = 500
        try:
            executor = pipeline._get_executor()
            cap = getattr(executor, "_max_limit", None)
            if isinstance(cap, int):
                max_documents = cap
        except Exception:
            pass

        max_time_ms = 30_000
        rate_limit: dict[str, Any] | None = None
        if settings is not None:
            max_time_ms = getattr(settings, "max_time_ms", max_time_ms)
            rps = getattr(settings, "rate_limit_rps", 0.0)
            if rps and rps > 0:
                rate_limit = {
                    "rps": rps,
                    "burst": getattr(settings, "rate_limit_burst", 0),
                }

        return {
            "max_documents": max_documents,
            "max_time_ms": max_time_ms,
            "rate_limit": rate_limit,
        }

    @mcp.tool(
        description=(
            "Discover what THIS agent may do: backend, supported/unsupported "
            "capabilities, limits, and per-collection permitted actions with "
            "per-action risk + approval requirement.\n"
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
        unsupported_values = sorted(c.value for c in Capability if c not in supported_caps)
        limits = _limits_block(pipeline)

        if policy is None:
            return ok(
                {
                    "backend": backend_name,
                    "supported_capabilities": supported_values,
                    "unsupported_capabilities": unsupported_values,
                    "agent": agent,
                    "mode": None,
                    "limits": limits,
                    "collections": {},
                    "connections_allow": [],
                    "note": "no policy configured — run guardmcp_setup",
                }
            )

        # Candidate action set per mode. The DECISION for each comes from
        # evaluate(), not from inline allow/deny rules.
        candidate_actions = set(_READ_ACTIONS)
        if policy.mode == "readwrite":
            candidate_actions |= set(WRITE_ACTIONS)

        # Drop actions whose capability the active backend cannot perform — an
        # unsupported action is impossible regardless of policy. (The engine also
        # honors this, but pruning here keeps the candidate set honest.)
        candidate_actions = {
            a
            for a in candidate_actions
            if ACTION_TO_CAPABILITY.get(a) is None or ACTION_TO_CAPABILITY[a] in supported_caps
        }
        ordered_actions = sorted(candidate_actions, key=lambda a: a.value)

        def _allowed_action_entries(col: str) -> list[dict[str, Any]]:
            """DERIVE permitted actions for a collection through the engine.

            Calls pipeline.evaluate(agent, col, action, {}) per candidate and keeps
            only ALLOWED / APPROVAL_REQUIRED. DENIED actions are excluded.
            """
            entries: list[dict[str, Any]] = []
            for act in ordered_actions:
                result = pipeline.evaluate(agent, col, act, {})
                status = result.decision.status
                if status not in (
                    DecisionStatus.ALLOWED,
                    DecisionStatus.APPROVAL_REQUIRED,
                ):
                    continue
                cap = ACTION_TO_CAPABILITY.get(act)
                risk = result.decision.risk
                entries.append(
                    {
                        "action": act.value,
                        "capability": cap.value if cap else None,
                        "decision": status.value,
                        "risk": risk.value if risk else None,
                        "approval_required": status == DecisionStatus.APPROVAL_REQUIRED,
                    }
                )
            return entries

        # Determine target collections from the policy (the engine still has the
        # final say per (collection, action) via evaluate()).
        executor = pipeline._get_executor()
        try:
            known_cols = await executor.list_collections()
        except Exception:
            known_cols = []

        allow_cols = policy.collections.allow
        deny_cols = set(policy.collections.deny)
        if "*" in allow_cols:
            target_cols = [c for c in known_cols if c not in deny_cols]
        elif allow_cols:
            target_cols = [c for c in allow_cols if c not in deny_cols]
        else:
            # AD-1: empty allow = deny-all ⇒ no collections are accessible.
            target_cols = []

        # Cap enumeration so a wildcard over many collections stays cheap.
        truncated = len(target_cols) > _MAX_COLLECTIONS
        if truncated:
            target_cols = target_cols[:_MAX_COLLECTIONS]

        collections_map: dict[str, dict[str, Any]] = {}
        for col in target_cols:
            collections_map[col] = {
                "actions": _allowed_action_entries(col),
                "masked_fields": policy.mask_fields_for(col),
                "fields_allow": policy.fields_allow,
            }

        data: dict[str, Any] = {
            "backend": backend_name,
            "supported_capabilities": supported_values,
            "unsupported_capabilities": unsupported_values,
            "agent": agent,
            "mode": policy.mode,
            "limits": limits,
            "collections": collections_map,
            "connections_allow": policy.connections_allow,
        }
        if truncated:
            data["truncated"] = True
            data["note"] = (
                f"collection enumeration capped at {_MAX_COLLECTIONS}; "
                "more collections exist but are not listed."
            )
        return ok(data)
