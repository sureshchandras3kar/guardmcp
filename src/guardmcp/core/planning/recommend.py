from __future__ import annotations

from ..interfaces.cost import CostLevel
from .models import AlternativePlan, ExecutionPlan

_COST_RANK = {
    CostLevel.LOW: 0, CostLevel.MEDIUM: 1, CostLevel.HIGH: 2,
    CostLevel.CRITICAL: 3, CostLevel.UNKNOWN: 2,
}
_GOV_PENALTY = {"denied": 2, "approval_required": 1}


class RecommendationEngine:
    def rank(self, plans: list[ExecutionPlan]) -> list[AlternativePlan]:
        def score(plan: ExecutionPlan) -> tuple[int, int, int]:
            gov = _GOV_PENALTY.get(str(plan.governance.get("decision", "")).lower(), 0)
            cost = _COST_RANK.get(plan.est_cost.estimated_cost, 2) if plan.est_cost else 2
            idx = 0 if plan.index_used else 1
            return (gov, cost, idx)

        ordered = sorted(enumerate(plans), key=lambda pair: (score(pair[1]), pair[0]))
        result: list[AlternativePlan] = []
        for rank, (_, plan) in enumerate(ordered, start=1):
            data = plan.model_dump()
            data.pop("rank", None)
            data.pop("tradeoff", None)
            tradeoff = getattr(plan, "tradeoff", "") or self._tradeoff(plan)
            result.append(AlternativePlan(**data, rank=rank, tradeoff=tradeoff))
        return result

    @staticmethod
    def _tradeoff(plan: ExecutionPlan) -> str:
        cost = plan.est_cost.estimated_cost.value if plan.est_cost else "UNKNOWN"
        base = "index-backed" if plan.index_used else "collection scan"
        return f"{base}, {cost} cost"
