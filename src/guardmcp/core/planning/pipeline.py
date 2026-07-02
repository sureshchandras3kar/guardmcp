from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from .ambiguity import AmbiguityDetector
from .models import AmbiguityReport, PlannerResult, PlanningContext, RelationshipGraph
from .planner import AlternativePlanner, QueryPlanner, indexed_fields
from .recommend import RecommendationEngine
from .relationships import RelationshipResolver

if TYPE_CHECKING:
    from ..pipeline import GuardPipeline

_WORD_RE = re.compile(r"[a-zA-Z_]+")


class PlanningPipeline:
    def __init__(
        self,
        guard: GuardPipeline,
        resolver: RelationshipResolver,
        get_plugin: Callable[[], object | None],
        *,
        ambiguity: AmbiguityDetector | None = None,
        planner: QueryPlanner | None = None,
        alternatives: AlternativePlanner | None = None,
        recommender: RecommendationEngine | None = None,
    ) -> None:
        self._guard = guard
        self._resolver = resolver
        self._get_plugin = get_plugin
        self._ambiguity = ambiguity or AmbiguityDetector()
        self._planner = planner or QueryPlanner()
        self._alternatives = alternatives or AlternativePlanner()
        self._recommender = recommender or RecommendationEngine()

    async def relationships(self, agent: str) -> RelationshipGraph:
        allowed = await self._guard.discover_collections(agent)
        return await self._resolver.graph(allowed)

    def _pick_resource(
        self, intent: str, resource: str | None, allowed: list[str], notes: list[str]
    ) -> str:
        if resource and resource in allowed:
            return resource
        if resource and resource not in allowed:
            notes.append(f"requested resource '{resource}' not authorized; picking another")
        tokens = set(_WORD_RE.findall(intent.lower()))
        singular_tokens = {t.rstrip("s") for t in tokens}
        for r in allowed:
            rl = r.lower()
            rl_sing = rl.rstrip("s")
            if rl in tokens or rl_sing in tokens or rl in singular_tokens or rl_sing in singular_tokens:  # noqa: E501
                return r
        notes.append(f"no resource named in intent; defaulted to '{allowed[0]}'")
        return allowed[0]

    async def _indexes_for(self, resource: str, notes: list[str]) -> list[dict]:
        plugin = self._get_plugin()
        executor = getattr(plugin, "_executor", None)
        getter = getattr(executor, "collection_indexes", None)
        if getter is None:
            return []
        try:
            return await getter(resource)
        except Exception:
            notes.append(f"index introspection failed for '{resource}'")
            return []

    async def plan(self, agent: str, intent: str, resource: str | None = None) -> PlannerResult:
        notes: list[str] = []
        empty_graph = RelationshipGraph(
            nodes=[], edges=[], generated_at=datetime.now(UTC).isoformat()
        )

        allowed = await self._guard.discover_collections(agent)
        if not allowed:
            notes.append("no authorized collections for this agent")
            return PlannerResult(
                ambiguity=AmbiguityReport(ambiguous=False, confidence=1.0),
                relationships=empty_graph, notes=notes,
            )

        chosen = self._pick_resource(intent, resource, allowed, notes)
        desc = await self._guard.describe_collection(agent, chosen)
        schema_fields = (desc or {}).get("fields", {})
        if desc is None:
            notes.append(f"no schema available for '{chosen}'")

        graph = await self._resolver.graph(allowed)
        indexes = await self._indexes_for(chosen, notes)
        idx_set = indexed_fields(indexes)

        report = self._ambiguity.detect(intent, schema_fields, idx_set)
        if report.ambiguous:
            notes.append("intent is ambiguous; returning interpretations for clarification")
            return PlannerResult(ambiguity=report, relationships=graph, notes=notes)

        ctx = PlanningContext(
            agent=agent, intent=intent, resource=chosen, allowed_resources=allowed,
            resource_schema={"fields": schema_fields}, indexes=indexes, relationships=graph,
        )
        interp = report.interpretations[0] if report.interpretations else None
        base = self._planner.build(ctx, interp)
        plugin = self._get_plugin()
        # Dialect-specific alternatives (e.g. Mongo aggregate pipelines) are built
        # by the active plugin, not core — see AlternativePlanner.expand.
        plans = self._alternatives.expand(base, ctx, plugin)

        enriched = []
        for plan in plans:
            est = None
            if plugin is not None and hasattr(plugin, "estimate"):
                try:
                    est = await plugin.estimate(plan.request)
                except Exception:
                    est = None
            ev = self._guard.evaluate_capability(
                agent, plan.request.resource, plan.request.capability, plan.request
            )
            gov = {"decision": ev.decision.status.value, "reason": ev.decision.reason}
            risk = ev.decision.risk.value if ev.decision.risk else None
            enriched.append(
                plan.model_copy(update={"est_cost": est, "governance": gov, "risk_level": risk})
            )

        ranked = self._recommender.rank(enriched)
        recommended = next(
            (p for p in ranked if str(p.governance.get("decision", "")).lower() != "denied"),
            None,
        )
        if recommended is None and ranked:
            notes.append("all candidate plans are denied by policy; no plan recommended")
        return PlannerResult(
            ambiguity=report, relationships=graph, plans=ranked,
            recommended_plan=recommended, notes=notes,
        )
