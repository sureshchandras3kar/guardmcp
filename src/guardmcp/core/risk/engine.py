from typing import Any

from ..interfaces.cost import CostEstimate, CostLevel
from ..models.domain import Action, RiskLevel

# Ordering for the coarse risk ladder, so escalation can take the MAX without a
# fragile chain of if/elif. Higher index = more severe.
_RISK_ORDER: list[RiskLevel] = [
    RiskLevel.LOW,
    RiskLevel.MEDIUM,
    RiskLevel.HIGH,
    RiskLevel.CRITICAL,
]

# A cost level maps to the MINIMUM risk it justifies. Expensive plans (collection
# scan / huge scan) floor risk at HIGH/CRITICAL.
_COST_TO_MIN_RISK: dict[CostLevel, RiskLevel] = {
    CostLevel.HIGH: RiskLevel.HIGH,
    CostLevel.CRITICAL: RiskLevel.CRITICAL,
}

_RISK_MAP: dict[Action, RiskLevel] = {
    # Read
    Action.FIND: RiskLevel.LOW,
    Action.COUNT: RiskLevel.LOW,
    Action.EXPLAIN: RiskLevel.LOW,
    # Introspection (safe reads)
    Action.COLLECTION_SCHEMA: RiskLevel.LOW,
    Action.COLLECTION_INDEXES: RiskLevel.LOW,
    Action.LIST_DATABASES: RiskLevel.LOW,
    Action.DB_STATS: RiskLevel.LOW,
    Action.COLLECTION_STORAGE_SIZE: RiskLevel.LOW,
    Action.MONGODB_LOGS: RiskLevel.LOW,
    # Write
    Action.AGGREGATE: RiskLevel.HIGH,  # was MEDIUM — can scan entire collections
    # HIGH: $currentOp exposes OTHER agents'/connections' running operations
    # (cross-tenant visibility); $changeStream is a long-lived stream bounded
    # to a short best-effort window by the executor, not a cheap read.
    Action.AGGREGATE_DB: RiskLevel.HIGH,
    Action.INSERT_ONE: RiskLevel.MEDIUM,
    Action.INSERT_MANY: RiskLevel.MEDIUM,
    Action.UPDATE_ONE: RiskLevel.HIGH,
    Action.UPDATE_MANY: RiskLevel.HIGH,
    Action.DELETE_ONE: RiskLevel.HIGH,
    Action.DELETE_MANY: RiskLevel.CRITICAL,
    # DDL
    Action.CREATE_INDEX: RiskLevel.MEDIUM,
    Action.DROP_INDEX: RiskLevel.HIGH,
    Action.DROP: RiskLevel.CRITICAL,
    Action.CREATE_COLLECTION: RiskLevel.MEDIUM,
    Action.RENAME_COLLECTION: RiskLevel.HIGH,
}


# S-4: actions whose blast radius depends on filter SCOPE. An empty/missing
# filter on a mutation hits the whole collection — far more dangerous than a
# targeted change — so it escalates to CRITICAL.
_SCOPE_SENSITIVE: frozenset[Action] = frozenset(
    {
        Action.UPDATE_ONE,
        Action.UPDATE_MANY,
        Action.DELETE_ONE,
        Action.DELETE_MANY,
    }
)


def _is_unscoped(filter_: Any) -> bool:
    """True if the filter targets the whole collection (empty or missing)."""
    return not filter_ or (isinstance(filter_, dict) and len(filter_) == 0)


class RiskEngine:
    def classify(self, action: Action, params: dict[str, Any] | None = None) -> RiskLevel:
        """
        Classify the risk of an action.

        S-4 scope escalation: when `params` is supplied and a mutation has an
        empty/missing filter (collection-wide blast radius), escalate to
        CRITICAL. Called without `params`, returns the static action-type risk
        (backward compatible).
        """
        base = _RISK_MAP.get(action, RiskLevel.CRITICAL)
        if params is not None and action in _SCOPE_SENSITIVE and _is_unscoped(params.get("filter")):
            return RiskLevel.CRITICAL
        return base

    def escalate_for_cost(self, base: RiskLevel, cost: CostEstimate) -> RiskLevel:
        """ADDITIVE, OPT-IN cost-aware escalation. Returns max(base, cost-floor):
        a HIGH/CRITICAL estimated cost (collection scan / huge scan) bumps the
        risk up; a cheap or UNKNOWN estimate leaves it untouched.

        Deliberately NOT wired into the synchronous classify()/evaluate() hot
        path — estimation needs a DB round-trip, and live authorization must stay
        cheap. It is available for guardmcp_plan (which already does the round-trip
        for the cost block) and for a FUTURE opt-in policy rule. See the
        ``max_cost`` policy seam documented in core/policy/models.py.
        """
        floor = _COST_TO_MIN_RISK.get(cost.estimated_cost)
        if floor is None:
            return base
        return max(base, floor, key=_RISK_ORDER.index)
