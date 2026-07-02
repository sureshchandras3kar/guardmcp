"""guardmcp_plan_query — NL intent → ambiguity, relationships, ranked plans.

Deterministic, no-LLM. NEVER executes queries; only reads authorized metadata,
estimates cost (explain), and evaluates governance per candidate plan.
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ....core.planning.pipeline import PlanningPipeline
from ....core.planning.relationships import RelationshipResolver
from .._common import ErrorCode, ToolContext, _active_plugin, err, ok


def register(mcp: FastMCP, ctx: ToolContext) -> None:
    get_pipeline = ctx.get_pipeline
    get_agent = ctx.get_agent
    _RO = ctx.RO

    def _build_planning_pipeline():
        pipeline = get_pipeline()
        get_plugin = lambda: _active_plugin(pipeline)  # noqa: E731
        resolver = RelationshipResolver(get_plugin)
        return PlanningPipeline(pipeline, resolver, get_plugin), get_agent()

    @mcp.tool(
        description=(
            "Plan a query from a natural-language intent WITHOUT executing it. "
            "Returns detected ambiguity (with interpretations to clarify), a "
            "relationship graph, ranked candidate execution plans (each with cost, "
            "index usage, and governance impact), and a recommended plan.\n"
            "Use when: deciding HOW to query before running read/aggregate ops.\n"
            "Do NOT use when: you already know the exact op — call guardmcp_plan.\n"
            "Side effects: none — never executes; only reads metadata + explain.\n"
            "Example: guardmcp_plan_query(intent='show active users')"
        ),
        annotations=_RO,
    )
    async def guardmcp_plan_query(intent: str, resource: str | None = None) -> str:
        try:
            planner, agent = _build_planning_pipeline()
            result = await planner.plan(agent, intent, resource)
            return ok(result.model_dump(mode="json"))
        except Exception as exc:  # planning must never crash the server
            return err(
                ErrorCode.BACKEND_ERROR,
                f"planning failed: {type(exc).__name__}",
                retryable=True,
            )

    @mcp.tool(
        description=(
            "Return the discovered relationship graph among the collections this "
            "agent is authorized to see (diagnostic / visualization).\n"
            "Side effects: none.\n"
            "Example: guardmcp_relationships()"
        ),
        annotations=_RO,
    )
    async def guardmcp_relationships(resource: str | None = None) -> str:
        try:
            planner, agent = _build_planning_pipeline()
            graph = await planner.relationships(agent)
            return ok({"relationships": graph.model_dump(mode="json")})
        except Exception as exc:
            return err(
                ErrorCode.BACKEND_ERROR,
                f"relationship discovery failed: {type(exc).__name__}",
                retryable=True,
            )
