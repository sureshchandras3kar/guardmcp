"""guardmcp_plan — dry-run preview of authorization/risk/affected docs + cost."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ....core.models.domain import Action
from ....core.validation import JsonList
from .._common import (
    Any,
    ErrorCode,
    FilterParam,
    ToolContext,
    UpdateParam,
    err,
    ok,
)

# Actions whose cost is the cost of SCANNING their filter — for these we estimate
# the equivalent READ (same resource + filter), since the blast-radius/scan cost
# is what matters. Reads/counts/aggregates estimate themselves.
_SCAN_LIKE_ACTIONS = {
    Action.UPDATE_ONE,
    Action.UPDATE_MANY,
    Action.DELETE_ONE,
    Action.DELETE_MANY,
}


async def _estimate_cost(pipeline, collection: str, act: Action, params: dict):
    """Best-effort normalized cost estimate for an operation. NEVER raises:
    returns ``(cost_dict, CostEstimate | None)``. On any failure → an UNKNOWN
    cost dict (+ warning) and None for the model. The raw explain is never
    exposed — only the normalized CostEstimate fields."""
    from ....core.interfaces.capability import (
        ACTION_TO_CAPABILITY,
        Capability,
        CapabilityRequest,
    )
    from ....core.interfaces.cost import CostEstimate, CostLevel

    def _unknown(msg: str):
        est = CostEstimate(estimated_cost=CostLevel.UNKNOWN, warnings=[msg])
        return est.model_dump(mode="json"), est

    try:
        from .._common import _active_plugin

        plugin = _active_plugin(pipeline)
        if plugin is None:
            return _unknown("no active backend plugin for estimation")

        # Map the action to the capability whose scan cost we want.
        capability: Capability | None
        if act in _SCAN_LIKE_ACTIONS or act == Action.COUNT:
            capability = Capability.READ
        else:
            capability = ACTION_TO_CAPABILITY.get(act)
        if capability not in (Capability.READ, Capability.AGGREGATE):
            return _unknown(f"estimation not applicable for action '{act.value}'")

        req = CapabilityRequest(
            capability=capability,
            resource=collection,
            filter=params.get("filter"),
            pipeline=params.get("pipeline"),
        )
        estimate = await plugin.estimate(req)
        return estimate.model_dump(mode="json"), estimate
    except Exception as exc:  # estimation must NEVER fail the plan
        return _unknown(f"cost estimation unavailable: {type(exc).__name__}")


def register(mcp: FastMCP, ctx: ToolContext) -> None:
    get_pipeline = ctx.get_pipeline
    get_agent = ctx.get_agent
    _RO = ctx.RO

    @mcp.tool(
        description=(
            "Preview authorization, risk, approval requirement, and affected-document "
            "estimate for an operation WITHOUT executing it. Call before any write.\n"
            "Use when: planning an update/delete and you want to know blast radius first.\n"
            "Do NOT use when: you actually intend to run the op — call the op tool.\n"
            "Side effects: none — never executes the write (may run a COUNT for estimates).\n"
            "Example: guardmcp_plan(collection='users', action='delete_many', filter={})"
        ),
        annotations=_RO,
    )
    async def guardmcp_plan(
        collection: str,
        action: str,
        filter: FilterParam = None,
        update: UpdateParam = None,
        documents: JsonList = None,
        pipeline_stages: JsonList = None,
    ) -> str:
        pipeline = get_pipeline()
        agent = get_agent()

        try:
            act = Action(action)
        except ValueError:
            valid = sorted(a.value for a in Action)
            return err(
                ErrorCode.VALIDATION,
                f"unknown action '{action}'. Valid actions: {valid}",
                retryable=False,
            )

        params: dict[str, Any] = {}
        if filter is not None:
            params["filter"] = filter
        if update is not None:
            params["update"] = update
        if documents is not None:
            params["documents"] = documents
        if pipeline_stages is not None:
            params["pipeline"] = pipeline_stages

        from ....core.models.domain import DecisionStatus

        eval_result = pipeline.evaluate(agent, collection, act, params)
        decision = eval_result.decision

        approval_required = decision.status == DecisionStatus.APPROVAL_REQUIRED

        # would_affect: best-effort COUNT for mutations (never executes the write).
        would_affect: int | None = None
        if act in _SCAN_LIKE_ACTIONS:
            count_eval = pipeline.evaluate(
                agent, collection, Action.COUNT, {"filter": filter or {}}
            )
            if count_eval.decision.status != DecisionStatus.DENIED:
                count_res = await pipeline.run(
                    agent, collection, Action.COUNT, {"filter": filter or {}}
                )
                if count_res.get("status") == "success":
                    data = count_res.get("data")
                    if isinstance(data, dict):
                        would_affect = data.get("count")
                    elif isinstance(data, int):
                        would_affect = data

        # Feature 1: best-effort cost estimate. Runs the backend's native explain
        # through the plugin (a DB round-trip) and normalizes to a CostEstimate —
        # NEVER the raw plan. Wrapped so estimation can NEVER fail the plan: on any
        # error (no plugin, explain failure, unsupported op) we emit UNKNOWN + a
        # warning. This is the only place the round-trip happens; synchronous
        # authorization stays cheap and is untouched.
        cost_block, cost_estimate = await _estimate_cost(pipeline, collection, act, params)

        # Cost-aware risk (additive): surface what the risk WOULD be if a future
        # policy opted into cost escalation. Does NOT change the live decision.
        base_risk = decision.risk
        cost_aware_risk = None
        if base_risk is not None and cost_estimate is not None:
            cost_aware_risk = pipeline._risk_engine.escalate_for_cost(
                base_risk, cost_estimate
            ).value

        return ok(
            {
                "decision": decision.status.value,
                "risk": decision.risk.value if decision.risk else None,
                "approval_required": approval_required,
                "policy_reason": decision.reason,
                "would_affect": would_affect,
                "cost": cost_block,
                "cost_aware_risk": cost_aware_risk,
            }
        )
