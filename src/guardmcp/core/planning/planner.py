from __future__ import annotations

import re

from ..interfaces.capability import Capability, CapabilityRequest
from .models import AlternativePlan, ExecutionPlan, Interpretation, PlanningContext

_TOP_WORDS = ("top", "highest", "most", "largest")
_LIMIT_WORDS = ("top", "first", "last", "latest", "limit")
_INT_RE = re.compile(r"\b(\d+)\b")
_WORD_RE = re.compile(r"[a-zA-Z_]+")


def indexed_fields(indexes: list[dict]) -> set[str]:
    fields: set[str] = set()
    for idx in indexes:
        for pair in idx.get("key", []):
            fields.add(pair[0] if isinstance(pair, (list, tuple)) else pair)
    return fields


def _detect_limit(intent: str) -> int | None:
    lower = intent.lower()
    if not any(w in lower for w in _LIMIT_WORDS):
        return None
    m = _INT_RE.search(lower)
    return int(m.group(1)) if m else None


def _detect_sort(intent: str, schema_fields: dict) -> dict | None:
    lower = intent.lower()
    if not any(w in lower for w in _TOP_WORDS):
        return None
    # sort by a schema field mentioned after "by", else any numeric field mentioned
    tokens = _WORD_RE.findall(lower)
    if "by" in tokens:
        tokens = tokens[tokens.index("by") + 1:]
    for tok in tokens:
        if tok in schema_fields:
            return {tok: -1}
    return None


class QueryPlanner:
    def build(
        self, context: PlanningContext, interpretation: Interpretation | None
    ) -> ExecutionPlan:
        schema_fields = context.resource_schema.get("fields", {}) if context.resource_schema else {}
        idx = indexed_fields(context.indexes)
        filter_: dict | None = None
        if interpretation is not None:
            filter_ = {interpretation.field: interpretation.value}
        sort = _detect_sort(context.intent, schema_fields)
        limit = _detect_limit(context.intent)
        req = CapabilityRequest(
            capability=Capability.READ,
            resource=context.resource or "",
            filter=filter_,
            sort=sort,
            limit=limit,
        )
        index_used: bool | None = None
        if filter_:
            index_used = next(iter(filter_)) in idx
        strategy = "index_scan" if index_used else "collection_scan"
        return ExecutionPlan(
            strategy=strategy,
            request=req,
            index_used=index_used,
            complexity="low" if index_used else "high",
        )


class AlternativePlanner:
    def expand(
        self,
        base: ExecutionPlan,
        context: PlanningContext,
        plugin: object | None = None,
    ) -> list[ExecutionPlan]:
        """Return the base plan plus any dialect-specific alternatives.

        core/planning is database-agnostic, so it never constructs a
        dialect-shaped request itself. It asks the active `plugin` (via the
        DatabasePlugin.alternative_requests seam) for alternative forms of
        `base.request` and wraps each into an AlternativePlan verbatim. Without a
        plugin — or with one that offers no alternatives — only the base plan is
        returned."""
        plans: list[ExecutionPlan] = [base]
        build_alternatives = getattr(plugin, "alternative_requests", None)
        if build_alternatives is None:
            return plans
        for alt in build_alternatives(base.request):
            plans.append(
                AlternativePlan(
                    strategy=alt.strategy,
                    request=alt.request,
                    complexity=alt.complexity,
                    tradeoff=alt.tradeoff,
                )
            )
        return plans
