"""guardmcp_plan_query — NL intent → ambiguity, relationships, ranked plans.

Deterministic, no-LLM. NEVER executes queries; only reads authorized metadata,
estimates cost (explain), and evaluates governance per candidate plan.
"""
from __future__ import annotations

import hashlib
import json

from mcp.server.fastmcp import FastMCP

from ....core.planning.cross_db import compose_transitive_paths
from ....core.planning.cross_db_resolver import CrossDatabaseResolver
from ....core.planning.pipeline import PlanningPipeline
from ....core.planning.relationships import (
    DEFAULT_CENTRALITY_TOP_N,
    RelationshipResolver,
    rank_by_centrality,
)
from .._common import (
    ErrorCode,
    ToolContext,
    VerbosityParam,
    _active_plugin,
    _strip_evidence,
    err,
    ok,
)


async def _cross_db_block(pipeline, agent: str) -> dict:
    """Cross-DB edges + transitive paths. ADDITIVE: never raises, degrades to
    empty lists (no databases_allow, no plugin, or any lookup failure)."""
    try:
        policy = pipeline._policies.get(agent) if pipeline._policies is not None else None
        allowed_dbs = list(policy.databases_allow) if policy else []
        if not allowed_dbs:
            return {"cross_db_edges": [], "cross_db_paths": []}
        resolver = CrossDatabaseResolver(pipeline, lambda: _active_plugin(pipeline))
        edges = await resolver.edges(agent, allowed_dbs)
        paths = compose_transitive_paths(edges)
        return {
            "cross_db_edges": [e.model_dump(by_alias=True) for e in edges],
            "cross_db_paths": [p.model_dump(by_alias=True) for p in paths],
        }
    except Exception:
        return {"cross_db_edges": [], "cross_db_paths": []}


def _semantics_stamp(fields: dict) -> str:
    """Deterministic content hash of a collection's semantics fields —
    independent of dict key order. Used for the opt-in repeat-call
    optimization below: the SAME fields always produce the SAME stamp, so an
    agent that echoes back a stamp it already has proves it already has this
    exact data (no server-side session state needed)."""
    canonical = json.dumps(fields, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


async def _semantics_block(
    pipeline, agent: str, graph, top_n: int, known_stamps: dict[str, str] | None = None
) -> tuple[dict, dict]:
    """Field semantics for the top-N most-connected collections (by relationship
    centrality) — bounded cost instead of one describe_collection per accessible
    collection. Each lookup is independently best-effort: one failing collection
    never drops the others.

    Opt-in repeat-call optimization (Option B — no server-side session state):
    if the caller's `known_stamps` already has the CURRENT stamp for a
    collection (meaning the agent already received this exact data in an
    earlier call), that collection's entry is replaced with a compact
    `{"unchanged_since": stamp}` instead of the full field dict. A stale,
    wrong, or absent stamp always falls back to the full dict — never a
    silent assumption. Returns (semantics, stamps): `stamps` should be
    remembered by the caller and echoed back as `known_stamps` next call.
    """
    known_stamps = known_stamps or {}
    semantics: dict[str, dict] = {}
    stamps: dict[str, str] = {}
    for name in rank_by_centrality(graph, top_n=top_n):
        try:
            desc = await pipeline.describe_collection(agent, name)
        except Exception:
            continue
        if not (desc and desc.get("semantics")):
            continue
        fields = desc["semantics"]
        stamp = _semantics_stamp(fields)
        stamps[name] = stamp
        if known_stamps.get(name) == stamp:
            semantics[name] = {"unchanged_since": stamp}
        else:
            semantics[name] = fields
    return semantics, stamps


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
            "verbosity='compact' strips the human-readable 'evidence' reasoning "
            "trace (kind/confidence/etc. are unaffected) — smaller response, same "
            "decision-relevant data. Default 'full' is unchanged.\n"
            "Example: guardmcp_plan_query(intent='show active users')"
        ),
        annotations=_RO,
    )
    async def guardmcp_plan_query(
        intent: str, resource: str | None = None, verbosity: VerbosityParam = "full"
    ) -> str:
        try:
            planner, agent = _build_planning_pipeline()
            result = await planner.plan(agent, intent, resource)
            data = result.model_dump(mode="json")
            if verbosity == "compact":
                data = _strip_evidence(data)
            return ok(data)
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
            "verbosity='compact' strips the human-readable 'evidence' reasoning "
            "trace (kind/confidence/etc. are unaffected) — smaller response, same "
            "decision-relevant data. Default 'full' is unchanged.\n"
            "Example: guardmcp_relationships()"
        ),
        annotations=_RO,
    )
    async def guardmcp_relationships(
        resource: str | None = None, verbosity: VerbosityParam = "full"
    ) -> str:
        try:
            planner, agent = _build_planning_pipeline()
            graph = await planner.relationships(agent)
            data: dict = {"relationships": graph.model_dump(mode="json")}
            data.update(await _cross_db_block(get_pipeline(), agent))
            if verbosity == "compact":
                data = _strip_evidence(data)
            return ok(data)
        except Exception as exc:
            return err(
                ErrorCode.BACKEND_ERROR,
                f"relationship discovery failed: {type(exc).__name__}",
                retryable=True,
            )

    @mcp.tool(
        description=(
            "One pre-flight context bundle: everything guardmcp_plan_query returns "
            "(ambiguity, relationships, ranked plans, recommended plan) PLUS "
            "cross-database edges/paths and field semantics for the most-connected "
            "collections — instead of calling guardmcp_plan_query and "
            "guardmcp_relationships separately.\n"
            "Use when: orienting before a NEW task against an unfamiliar schema.\n"
            "Do NOT use when: you already know the resource/plan — call the op "
            "tool or guardmcp_plan_query directly (this bundle costs more).\n"
            "Side effects: none — never executes; only reads metadata + explain.\n"
            "Note: semantics are capped to the top-N collections by relationship "
            "centrality (bounded cost, not one lookup per accessible collection).\n"
            "Note: response includes `semantics_stamps` — remember it and pass it "
            "back as `known_stamps` on a later call against the same collections "
            "to get a compact `{unchanged_since: stamp}` instead of the full "
            "semantics for anything that hasn't changed (saves tokens on repeat "
            "calls; falls back to full data if the stamp is stale/wrong/missing).\n"
            "verbosity='compact' strips the human-readable 'evidence' reasoning "
            "trace (kind/confidence/etc. are unaffected) — smaller response, same "
            "decision-relevant data. Default 'full' is unchanged.\n"
            "Example: guardmcp_context(intent='show active users')"
        ),
        annotations=_RO,
    )
    async def guardmcp_context(
        intent: str,
        resource: str | None = None,
        verbosity: VerbosityParam = "full",
        known_stamps: dict[str, str] | None = None,
    ) -> str:
        try:
            planner, agent = _build_planning_pipeline()
            pipeline = get_pipeline()
            result = await planner.plan(agent, intent, resource)
            data = result.model_dump(mode="json")
            data.update(await _cross_db_block(pipeline, agent))
            semantics, stamps = await _semantics_block(
                pipeline, agent, result.relationships, DEFAULT_CENTRALITY_TOP_N, known_stamps
            )
            data["semantics"] = semantics
            data["semantics_stamps"] = stamps
            total = len(result.relationships.nodes)
            if total > DEFAULT_CENTRALITY_TOP_N:
                data["notes"].append(
                    f"semantics capped to top {DEFAULT_CENTRALITY_TOP_N} of {total} "
                    "collections by relationship centrality"
                )
            if verbosity == "compact":
                data = _strip_evidence(data)
            return ok(data)
        except Exception as exc:  # bundling must never crash the server
            return err(
                ErrorCode.BACKEND_ERROR,
                f"context bundling failed: {type(exc).__name__}",
                retryable=True,
            )
