from ..interfaces.errors import ErrorCode
from ..models.domain import (
    DB_LEVEL_ACTIONS,
    WRITE_ACTIONS,
    Decision,
    DecisionStatus,
    Request,
    RiskLevel,
)
from ..validation import collection_permitted
from .models import Policy
from .trace import PolicyTrace


class PolicyEngine:
    def evaluate(
        self,
        request: Request,
        policy: Policy,
        risk: RiskLevel,
        trace: PolicyTrace | None = None,
    ) -> Decision:
        # Rule 1: readonly mode blocks all writes
        if policy.mode == "readonly" and request.action in WRITE_ACTIONS:
            if trace is not None:
                trace.add(
                    "policy",
                    "readonly_mode",
                    "matched",
                    f"action '{request.action.value}' blocked in readonly mode",
                )
            return Decision(
                status=DecisionStatus.DENIED,
                reason=(
                    f"action '{request.action.value}' is blocked in readonly mode. "
                    "Allowed actions: find, aggregate, count."
                ),
                risk=risk,
                code=ErrorCode.READONLY.value,
            )
        if trace is not None:
            trace.add(
                "policy",
                "readonly_mode",
                "passed",
                f"mode={policy.mode}",
            )

        # Rules 2–3: collection checks (skipped for DB-level actions).
        # AD-1: deny-by-default. collection_permitted() centralizes the
        # semantics — deny wins, "*" allows all, empty/non-matching allow DENIES.
        if request.action not in DB_LEVEL_ACTIONS:
            if not collection_permitted(
                request.collection,
                allow=policy.collections.allow,
                deny=policy.collections.deny,
            ):
                if request.collection in policy.collections.deny:
                    reason = f"collection '{request.collection}' is not permitted."
                    detail = f"collection '{request.collection}' in deny list"
                else:
                    reason = (
                        f"collection '{request.collection}' is not in the allowed list. "
                        f"Allowed: {sorted(policy.collections.allow)}."
                    )
                    detail = f"collection '{request.collection}' not in allow list"
                if trace is not None:
                    trace.add("policy", "collection_access", "matched", detail)
                return Decision(
                    status=DecisionStatus.DENIED,
                    reason=reason,
                    risk=risk,
                    code=ErrorCode.COLLECTION_NOT_ALLOWED.value,
                )
            if trace is not None:
                trace.add(
                    "policy",
                    "collection_access",
                    "passed",
                    f"collection '{request.collection}' permitted",
                )
        elif trace is not None:
            trace.add(
                "policy",
                "collection_access",
                "skipped",
                f"action '{request.action.value}' is DB-level (no collection)",
            )

        # Rule 4: explicit action deny
        if request.action.value in policy.actions.deny:
            if trace is not None:
                trace.add(
                    "policy",
                    "action_deny",
                    "matched",
                    f"action '{request.action.value}' explicitly denied",
                )
            return Decision(
                status=DecisionStatus.DENIED,
                reason=(
                    f"action '{request.action.value}' is explicitly denied. "
                    f"Denied actions: {sorted(policy.actions.deny)}."
                ),
                risk=risk,
                code=ErrorCode.ACTION_NOT_ALLOWED.value,
            )
        if trace is not None:
            trace.add("policy", "action_deny", "passed", None)

        # Rule 5: action allow-list (if set, must be in it)
        if policy.actions.allow and request.action.value not in policy.actions.allow:
            if trace is not None:
                trace.add(
                    "policy",
                    "action_allow",
                    "matched",
                    f"action '{request.action.value}' not in allow list",
                )
            return Decision(
                status=DecisionStatus.DENIED,
                reason=(
                    f"action '{request.action.value}' is not in the allowed list. "
                    f"Allowed: {sorted(policy.actions.allow)}."
                ),
                risk=risk,
                code=ErrorCode.ACTION_NOT_ALLOWED.value,
            )
        if trace is not None:
            trace.add(
                "policy",
                "action_allow",
                "passed",
                "no allow-list restriction"
                if not policy.actions.allow
                else f"action '{request.action.value}' in allow list",
            )

        # Rule 6: approval gates
        if risk == RiskLevel.CRITICAL and policy.approval.critical:
            if trace is not None:
                trace.add(
                    "approval",
                    "approval_critical",
                    "matched",
                    "CRITICAL risk requires approval",
                )
            return Decision(
                status=DecisionStatus.APPROVAL_REQUIRED,
                reason=(
                    f"action '{request.action.value}' is classified as CRITICAL risk "
                    "and requires human approval."
                ),
                risk=risk,
            )
        if risk == RiskLevel.HIGH and policy.approval.high:
            if trace is not None:
                trace.add(
                    "approval",
                    "approval_high",
                    "matched",
                    "HIGH risk requires approval",
                )
            return Decision(
                status=DecisionStatus.APPROVAL_REQUIRED,
                reason=(
                    f"action '{request.action.value}' is classified as HIGH risk "
                    "and requires human approval."
                ),
                risk=risk,
            )
        if trace is not None:
            trace.add(
                "approval",
                "approval_gate",
                "passed",
                f"risk={risk.value} does not require approval",
            )

        if trace is not None:
            trace.add("policy", "default_allow", "matched", "request permitted by policy")
        return Decision(
            status=DecisionStatus.ALLOWED,
            reason="request permitted by policy.",
            risk=risk,
        )
