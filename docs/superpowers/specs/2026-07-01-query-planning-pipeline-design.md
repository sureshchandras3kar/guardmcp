# Intelligent Query Planning Pipeline — Design

Date: 2026-07-01
Status: Approved (design), implementation Mongo-only (Phase 1)
Branch: `feat/query-planning-pipeline`

## Summary

A pre-execution **query planning pipeline** exposed through MCP. It analyzes a
natural-language intent against **authorized** database metadata and returns
structured, deterministic guidance — ambiguity report, relationship graph,
candidate execution plans with cost + governance impact, and a ranked
recommendation. It **never executes queries**, **never decides for the model**,
and **never bypasses governance**.

Identity guardrail: GuardMCP stays a *governance and database intelligence*
layer. No AI/LLM logic. The planner supplies facts + advisory recommendations;
the MCP client (Claude) does the reasoning and makes the final call.

## Design Rationale

The LLM never sees the database — only tool outputs. It therefore cannot
introspect four fact classes the planner supplies deterministically:

1. **Authorized surface** — policy allow/deny + masked fields.
2. **Indexes & statistics** — index-backed vs collection scan, cardinality.
3. **Discovered relationships** — FK (SQL, later), repeated identifiers,
   naming, index shape.
4. **Governed cost** — `CostEstimate` via native explain + per-plan policy/risk
   decision.

Without it, agents repeatedly: query denied/masked targets, pick the wrong
field ("active"), write unindexed scans, invent wrong joins, and trip approval
gates mid-task. Success is measured by eval deltas: first-query-correctness ↑,
denied-call rate ↓, index-backed-plan fraction ↑, ambiguity-caught rate ↑.

"Database intelligence" without AI = deterministic analysis over
database-derived facts, in the same sense as a query optimizer / `EXPLAIN`.
Every output traces to a metadata fact and is reproducible.

## Architecture (Approach A — thin core orchestrator, reuse existing seams)

Rejected alternatives: (B) a parallel IR + `PlannerPlugin` interface duplicates
`CapabilityRequest` and will diverge; (C) planning inside each plugin scatters
logic and duplicates security checks.

### Reuse map

| Need | Existing seam reused |
|---|---|
| Intermediate representation | `CapabilityRequest` (portable `filter` dialect + `predicate` AST + `joins`/`sort`) — the plan IS a not-yet-executed capability request |
| Cost / complexity / index usage | `DatabasePlugin.estimate() → CostEstimate/CostLevel` (safe default UNKNOWN) |
| Governance impact of a plan | `GuardPipeline.evaluate_capability()` / `evaluate()` — policy+risk, no execution |
| Authorized-only metadata | `discover_collections()` + `describe_collection()` — already policy-filter + mask |
| Static capability gating | `DatabasePlugin.manifest()` |
| Response envelope | `server/responses.py` `from_pipeline_result` shape |

### Module layout (new, database-agnostic)

```
src/guardmcp/core/planning/
    pipeline.py        # PlanningPipeline — orchestrates stages
    ambiguity.py       # AmbiguityDetector
    relationships.py   # RelationshipResolver (+ in-memory cache)
    planner.py         # QueryPlanner (+ cost normalization glue)
    alternatives.py    # AlternativePlanner
    recommend.py       # RecommendationEngine (ranks, never auto-selects)
    models.py          # planning DTOs (see below)
```

### Public MCP surface

> **Naming (resolved):** a `guardmcp_plan` tool ALREADY exists
> (`server/tools/meta/plan.py`) — a *concrete-operation* dry-run that previews
> `decision/risk/approval/would_affect/cost` for an op you already know. Write
> tools' docs instruct callers to run it first. We do NOT collide with or
> overload it. Our NL pipeline is a distinct, higher-level tool named
> **`guardmcp_plan_query`** (the name the original spec used).

- `guardmcp_plan_query` ⭐ — flagship. NL intent → runs the full pipeline,
  returns `{ambiguity, relationships, plans, recommended_plan, notes}`.
- `guardmcp_relationships` — optional diagnostic (graph only).
- Existing `guardmcp_plan` — **unchanged**; becomes the per-op preview the model
  calls on the chosen plan before executing.
- **No** standalone ambiguity / alternatives tools. One orchestration tool =
  fewer model tool-calls, less token/order ambiguity (compiler/optimizer
  pattern: many internal stages, one public operation).

Composition: `guardmcp_plan_query` (NL → ranked candidate `CapabilityRequest`s)
→ model picks → existing `guardmcp_plan` previews the concrete op → execute via
the normal read/write tools.

### Hard boundaries (enforced structurally)

- Planner reads metadata **only** via governed accessors + the new plugin
  metadata method → denied collections / masked fields are physically
  unreachable.
- Planner **never** calls `executor.execute()`. It may call `plugin.estimate()`
  (read-only explain) and `evaluate_capability()` (no execution).
- Output is advisory. `recommended_plan` = ranking + evidence, not authority.
- Planning calls are **audited** (same pattern as `discover_collections`).

## Planning Models (the IR + DTOs) — `planning/models.py`

```
Relationship        { from_resource, from_field, to_resource, to_field,
                      kind: fk|index|naming|sampled, confidence: float, evidence: str }
RelationshipGraph   { nodes: [resource], edges: [Relationship], generated_at, cached: bool }
AmbiguityReport     { ambiguous: bool, confidence: float,
                      interpretations: [{field, operator, value, confidence, evidence}],
                      recommendation: str }
PlanningContext     { agent, intent, resource, allowed_resources, schema, indexes, relationships }
ExecutionPlan       { strategy, request: CapabilityRequest, relationships_used,
                      est_cost: CostEstimate, complexity, index_used: bool, risk_level,
                      governance: {decision, requires_approval}, limitations: [str] }
AlternativePlan     = ExecutionPlan + { rank, tradeoff: str }
PlannerResult       { ambiguity, relationships, plans: [AlternativePlan],
                      recommended_plan, notes: [str] }
```

Core decision: **`ExecutionPlan.request` is a `CapabilityRequest`.** No new IR.
To execute, the model hands that request to the normal governed path.

## Request Lifecycle (one `guardmcp_plan` call)

```
ToolContext (agent, policy, active plugin)
   → PlanningPipeline.plan(agent, intent, resource?)
     1. PlanningContext ← discover_collections() + describe_collection()   [governed]
                          + RelationshipResolver.graph()                    [cached]
     2. AmbiguityDetector.detect(intent, context)
          if ambiguous & confidence < τ → SHORT-CIRCUIT: return ambiguity, no plans, "clarify"
     3. QueryPlanner.build(intent, context)      → base ExecutionPlan(s)
     4. AlternativePlanner.expand(base, context) → [ExecutionPlan]
     5. per plan: plugin.estimate(req) + evaluate_capability(req)  [cost + governance, NO execute]
        (SAME computation the existing guardmcp_plan tool performs per concrete op)
     6. RecommendationEngine.rank(plans)         → recommended_plan + reasons
   → PlannerResult (advisory; model decides & executes via existing tools)
```

## Determinism, Confidence, Failure

- **Deterministic**: same metadata + intent → same output. Sampling is
  seeded + capped.
- **Confidence** floats only on ambiguity interpretations + relationships.
  Plans carry a **cost class**, not a confidence score.
- **Stage failure = degrade + note**, never hard-fail the whole call (e.g. no
  relationships → still plan; append a `notes[]` warning). Ambiguity below
  threshold short-circuits with a clarify recommendation and no plans. Errors
  use existing `ErrorCode`.

## Plugin Change (Mongo-first)

Add one optional method to `DatabasePlugin` with a **safe default returning
empty**, so Postgres/MySQL/future plugins remain valid and integrate later with
zero engine changes (precedent: `estimate()`, `manifest()`):

```python
async def relationships(self, resources: list[str]) -> list[dict]:
    """Return normalized relationship hints for the given resources.
    Default: []. Only MongoPlugin implements this in Phase 1."""
    return []
```

MongoPlugin implements it via indexes + repeated-identifier / naming heuristics
+ optional bounded sampling. Postgres/MySQL (later) via `information_schema`
FKs — higher confidence, no core change.

Database-specific logic that stays in plugins: metadata collection,
relationship discovery, statistics, query translation, native explain.

## Security & Governance

- `evaluate_capability()` per plan returns the **same** decision the real call
  would get (incl. approval-required) — surfaced, not triggered.
- Metadata sourced only through collection-permission-filtered + masked
  accessors → restricted metadata cannot leak (adversarial test required).
- Denied plans are flagged; their underlying metadata never surfaces.
- No new connection/credential path; uses active `ToolContext`. Planning is
  audited.

## Performance

- Metadata: schema (bounded sample), indexes, collection stats, optional small
  relationship sample. `estimate()` via explain reads no data.
- **Cache**: relationship graph + schema per `(connection, resource)`.
- **Invalidate** on: `switch_connection`, policy hot-reload, TTL, explicit force.
- Latency: sub-second cached; cold path bounded by one explain + capped sample.
- No full scans, ever. Scales with metadata size, not data size.

## API / Response

Uses the existing envelope: `{status, data:{ambiguity, relationships, plans[],
recommended_plan, notes[]}, neutral?, meta}`. Partial results allowed
(short-circuit / degraded stages).

## Testing

- **Unit** per stage: ambiguity (golden files), relationship inference (known
  FK/naming fixtures), planner (IR shape), recommend ranking, cache
  invalidation.
- **Integration**: full `guardmcp_plan` against seeded Mongo; governance
  cross-check (plan `governance` == `evaluate_capability`).
- **Edges**: empty collection, no indexes, no relationships, ambiguous-no-match,
  single unambiguous interpretation, resource omitted.
- **Adversarial**: intent naming a denied/masked field must not leak;
  injection-shaped intent; oversized intent; pipeline referencing forbidden
  collection.
- Reuse `evals/` harness + per-backend fixtures.

## Future Evolution

- Additive only — new stages/fields don't change the public tool signature.
- Extension points now: plugin `relationships()` method, stage classes, cache
  layer, ranking strategy.
- `RelationshipResolver` + `AmbiguityDetector` become shared services for future
  schema-intelligence / NL tools.
- Future engines (Oracle/SQLServer/SQLite/Snowflake/BigQuery) implement only the
  metadata method; core unchanged.

## Scope — Phase 1 (this cycle)

MongoDB only. Full internal pipeline (all stages), one public tool
`guardmcp_plan` + diagnostic `guardmcp_relationships`. SQL plugins keep the
safe-default empty metadata method (no implementation yet).
