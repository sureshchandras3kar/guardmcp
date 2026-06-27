"""Policy-introspection tools: guardmcp_explain_policy + guardmcp_simulate_policy."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ....core.models.domain import Action, DecisionStatus
from ....core.validation import JsonDict
from .._common import (
    Any,
    ErrorCode,
    ToolContext,
    err,
    ok,
)


def register(mcp: FastMCP, ctx: ToolContext) -> None:
    get_pipeline = ctx.get_pipeline
    _RO = ctx.RO

    # ── Feature 2: policy explanation ───────────────────────────────────────────

    @mcp.tool(
        description=(
            "Explain WHY a (agent, collection, action) would be allowed, denied, or "
            "require approval — the ordered rule trace from the REAL evaluator.\n"
            "Use when: an op was blocked and you want the exact rule that decided it.\n"
            "Do NOT use when: you intend to run the op — call the op tool or guardmcp_plan.\n"
            "Side effects: none — read-only, never executes, no audit mutation.\n"
            "Example: guardmcp_explain_policy(agent='claude', collection='users', "
            "action='delete_one')"
        ),
        annotations=_RO,
    )
    async def guardmcp_explain_policy(
        agent: str,
        collection: str,
        action: str,
        connection: str | None = None,
    ) -> str:
        from ....core.policy.explain import build_explanation
        from ....core.policy.trace import PolicyTrace

        pipeline = get_pipeline()

        try:
            act = Action(action)
        except ValueError:
            valid = sorted(a.value for a in Action)
            return err(
                ErrorCode.VALIDATION,
                f"unknown action '{action}'. Valid actions: {valid}",
                retryable=False,
            )

        # SINGLE SOURCE OF TRUTH: same method authorization uses, with a trace.
        trace = PolicyTrace()
        eval_result = pipeline.evaluate(agent, collection, act, {}, trace=trace)
        explanation = build_explanation(eval_result.decision, trace)

        data: dict[str, Any] = {
            "decision": explanation.decision,
            "risk": explanation.risk,
            "approval_required": explanation.approval_required,
            "matched_rules": [
                {"rule": r.rule, "result": r.result} for r in explanation.matched_rules
            ],
            "evaluation_trace": explanation.evaluation_trace,
            "reason": explanation.reason,
            "code": explanation.code,
        }
        if connection is not None:
            # Switching is policy-gated; we only NOTE the requested connection.
            data["connection"] = connection
        return ok(data)

    # ── Feature 3: policy simulator (what-if) ───────────────────────────────────

    @mcp.tool(
        description=(
            "Simulate a proposed policy change WITHOUT applying it: evaluates the same "
            "request against current and proposed policies and reports the diff + impact.\n"
            "Use when: reviewing a policy edit and you want its blast radius before saving.\n"
            "Do NOT use when: you want to apply a policy — edit policy.yaml / guardmcp_setup.\n"
            "Side effects: none — never persists or executes the proposed policy.\n"
            "Example: guardmcp_simulate_policy(request={'agent':'claude','collection':'users',"
            "'action':'delete_one'}, proposed_policy={...})"
        ),
        annotations=_RO,
    )
    async def guardmcp_simulate_policy(
        request: JsonDict,
        proposed_policy: JsonDict | str,
        current_policy: JsonDict | str | None = None,
    ) -> str:
        from ....core.policy.explain import (
            build_policy_from_input,
            classify_impact,
            diff_policies,
        )

        pipeline = get_pipeline()

        if not request:
            return err(
                ErrorCode.VALIDATION,
                "request is required (agent, collection, action).",
                retryable=False,
            )
        agent = str(request.get("agent", ""))
        collection = str(request.get("collection", ""))
        action_str = str(request.get("action", ""))
        if not agent or not action_str:
            return err(
                ErrorCode.VALIDATION,
                "request must include 'agent' and 'action'.",
                retryable=False,
            )

        try:
            act = Action(action_str)
        except ValueError:
            valid = sorted(a.value for a in Action)
            return err(
                ErrorCode.VALIDATION,
                f"unknown action '{action_str}'. Valid actions: {valid}",
                retryable=False,
            )

        if proposed_policy is None or proposed_policy == "":
            return err(
                ErrorCode.VALIDATION,
                "proposed_policy is required.",
                retryable=False,
            )

        # Build Policy objects via the SAME loader parsing + inheritance.
        try:
            proposed = build_policy_from_input(proposed_policy, agent=agent)
        except Exception as exc:
            return err(
                ErrorCode.VALIDATION,
                f"invalid proposed_policy: {exc}",
                retryable=False,
            )

        if current_policy is None:
            current = pipeline._policies.get(agent)
        else:
            try:
                current = build_policy_from_input(current_policy, agent=agent)
            except Exception as exc:
                return err(
                    ErrorCode.VALIDATION,
                    f"invalid current_policy: {exc}",
                    retryable=False,
                )

        # SINGLE SOURCE OF TRUTH: run the SAME evaluate() against each policy via
        # the additive policy_override seam — no second evaluator.
        cur_eval = pipeline.evaluate(agent, collection, act, {}, policy_override=current)
        prop_eval = pipeline.evaluate(agent, collection, act, {}, policy_override=proposed)
        current_decision = cur_eval.decision.status.value
        proposed_decision = prop_eval.decision.status.value
        decision_changed = current_decision != proposed_decision

        # Diff requires two Policy objects. If no current policy exists, the diff
        # is the full proposed surface vs an empty baseline.
        if current is None:
            from ....core.policy.models import Policy as _Policy

            baseline = _Policy(agent=proposed.agent)
            changed_rules = diff_policies(baseline, proposed)
        else:
            changed_rules = diff_policies(current, proposed)

        impact = classify_impact(changed_rules, behavior_change=decision_changed)

        return ok(
            {
                "current_decision": current_decision,
                "proposed_decision": proposed_decision,
                "decision_changed": decision_changed,
                "risk": prop_eval.decision.risk.value if prop_eval.decision.risk else None,
                "approval_required": (proposed_decision == DecisionStatus.APPROVAL_REQUIRED.value),
                "changed_rules": changed_rules,
                "impact": {
                    "security": impact.security,
                    "behavior_change": impact.behavior_change,
                },
            }
        )
