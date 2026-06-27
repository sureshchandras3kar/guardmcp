"""
MongoDB-specific cost normalization.

Pure functions that turn a RAW MongoDB ``explain(executionStats)`` document into
the backend-neutral :class:`CostEstimate`. Kept separate from the executor (which
does I/O) so it is unit-testable with a canned explain dict and so the raw plan
never escapes this boundary — only the normalized estimate does.
"""

from __future__ import annotations

from typing import Any

from ...core.interfaces.cost import CostEstimate, classify_cost


def _winning_plan(explain: dict[str, Any]) -> dict[str, Any]:
    """Return the winningPlan, tolerating both find and aggregate shapes."""
    qp = explain.get("queryPlanner")
    if isinstance(qp, dict) and isinstance(qp.get("winningPlan"), dict):
        return qp["winningPlan"]
    # Aggregate explain nests the planner under stages[0]["$cursor"].
    stages = explain.get("stages")
    if isinstance(stages, list):
        for stage in stages:
            cursor = stage.get("$cursor") if isinstance(stage, dict) else None
            if isinstance(cursor, dict):
                inner = cursor.get("queryPlanner")
                if isinstance(inner, dict) and isinstance(inner.get("winningPlan"), dict):
                    return inner["winningPlan"]
    return {}


def _plan_stages(plan: dict[str, Any]) -> list[str]:
    """Flatten the (possibly nested) winningPlan into its stage names."""
    stages: list[str] = []
    node: Any = plan
    seen = 0
    while isinstance(node, dict) and seen < 64:  # bounded walk; plans are shallow
        stage = node.get("stage")
        if isinstance(stage, str):
            stages.append(stage)
        node = node.get("inputStage")
        seen += 1
    return stages


def _execution_stats(explain: dict[str, Any]) -> dict[str, Any]:
    es = explain.get("executionStats")
    return es if isinstance(es, dict) else {}


def normalize_mongo_explain(explain: dict[str, Any]) -> CostEstimate:
    """Normalize a raw Mongo explain(executionStats) dict → CostEstimate.

    Extracts totalDocsExamined / totalKeysExamined / nReturned /
    executionTimeMillis and the winning-plan stages (COLLSCAN →
    collection_scan, IXSCAN → index_used), then defers the LOW/MEDIUM/HIGH/
    CRITICAL bucketing to the SHARED ``classify_cost`` heuristic. NEVER returns
    the raw plan.
    """
    es = _execution_stats(explain)
    plan = _winning_plan(explain)
    stages = _plan_stages(plan)

    docs_examined = es.get("totalDocsExamined")
    keys_examined = es.get("totalKeysExamined")
    duration = es.get("executionTimeMillis")

    collection_scan = "COLLSCAN" in stages
    index_used = "IXSCAN" in stages or "IDHACK" in stages

    warnings: list[str] = []
    if collection_scan:
        warnings.append(
            "operation performs a collection scan (no index) — consider adding "
            "an index on the filtered field(s)"
        )

    level = classify_cost(
        estimated_documents=docs_examined,
        collection_scan=collection_scan if (collection_scan or index_used) else None,
        index_used=index_used if (collection_scan or index_used) else None,
    )

    return CostEstimate(
        estimated_documents=int(docs_examined) if docs_examined is not None else None,
        estimated_keys_examined=int(keys_examined) if keys_examined is not None else None,
        collection_scan=collection_scan if (collection_scan or index_used) else None,
        index_used=index_used if (collection_scan or index_used) else None,
        estimated_cost=level,
        estimated_duration_ms=int(duration) if duration is not None else None,
        warnings=warnings,
    )
