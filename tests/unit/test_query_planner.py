from guardmcp.core.interfaces.capability import Capability, CapabilityRequest
from guardmcp.core.interfaces.plugin import AlternativeRequest
from guardmcp.core.planning.models import (
    Interpretation,
    PlanningContext,
    RelationshipGraph,
)
from guardmcp.core.planning.planner import (
    AlternativePlanner,
    QueryPlanner,
    indexed_fields,
)


class _FakeAltPlugin:
    """Minimal plugin exposing only alternative_requests — stands in for a
    dialect plugin that turns a filtered read into an aggregate alternative.
    The Mongo pipeline shape lives HERE (in a plugin stub), never in core."""

    def alternative_requests(self, req: CapabilityRequest) -> list[AlternativeRequest]:
        if not req.filter:
            return []
        return [
            AlternativeRequest(
                request=CapabilityRequest(
                    capability=Capability.AGGREGATE,
                    resource=req.resource,
                    pipeline=[{"$match": req.filter}, {"$limit": req.limit or 50}],
                ),
                strategy="aggregation",
                complexity="medium",
                tradeoff="pipeline form; enables downstream grouping/joins",
            )
        ]


def _ctx(resource="user", intent="show active users", indexes=None, schema=None):
    return PlanningContext(
        agent="claude", intent=intent, resource=resource,
        allowed_resources=[resource],
        resource_schema={"fields": schema or {"status": "string", "revenue": "double"}},
        indexes=indexes or [],
        relationships=RelationshipGraph(nodes=[resource], edges=[], generated_at="t"),
    )


def test_indexed_fields_helper():
    idx = [{"name": "status_1", "key": [("status", 1)]}]
    assert indexed_fields(idx) == {"status"}


def test_build_read_plan_with_filter():
    interp = Interpretation(
        field="status", operator="=", value="ACTIVE", confidence=0.6, evidence="x"
    )
    plan = QueryPlanner().build(_ctx(), interp)
    assert plan.request.capability == Capability.READ
    assert plan.request.filter == {"status": "ACTIVE"}
    assert plan.strategy == "collection_scan"
    assert plan.index_used is False


def test_build_marks_index_used():
    interp = Interpretation(
        field="status", operator="=", value="ACTIVE", confidence=0.6, evidence="x"
    )
    ctx = _ctx(indexes=[{"name": "status_1", "key": [("status", 1)]}])
    plan = QueryPlanner().build(ctx, interp)
    assert plan.index_used is True
    assert plan.strategy == "index_scan"
    assert plan.complexity == "low"


def test_build_parses_top_n_sort_and_limit():
    ctx = _ctx(intent="top 10 users by revenue")
    plan = QueryPlanner().build(ctx, None)
    assert plan.request.limit == 10
    assert plan.request.sort == {"revenue": -1}


def test_alternative_planner_delegates_to_plugin():
    interp = Interpretation(
        field="status", operator="=", value="ACTIVE", confidence=0.6, evidence="x"
    )
    base = QueryPlanner().build(_ctx(), interp)
    alts = AlternativePlanner().expand(base, _ctx(), _FakeAltPlugin())
    strategies = {a.strategy for a in alts}
    assert "aggregation" in strategies
    agg = next(a for a in alts if a.strategy == "aggregation")
    # Dialect (pipeline) came from the plugin, wrapped verbatim into the plan.
    assert agg.request.pipeline[0] == {"$match": {"status": "ACTIVE"}}
    assert agg.tradeoff == "pipeline form; enables downstream grouping/joins"
    assert agg.complexity == "medium"


def test_alternative_planner_no_alternative_without_filter():
    base = QueryPlanner().build(_ctx(intent="list users"), None)
    alts = AlternativePlanner().expand(base, _ctx(intent="list users"), _FakeAltPlugin())
    assert all(a.strategy != "aggregation" for a in alts)


def test_alternative_planner_without_plugin_returns_only_base():
    interp = Interpretation(
        field="status", operator="=", value="ACTIVE", confidence=0.6, evidence="x"
    )
    base = QueryPlanner().build(_ctx(), interp)
    assert AlternativePlanner().expand(base, _ctx()) == [base]
    assert AlternativePlanner().expand(base, _ctx(), None) == [base]


def test_planner_core_is_free_of_dialect_tokens():
    """Invariant: core/planning stays database-agnostic — no Mongo/SQL literals."""
    import guardmcp.core.planning.planner as planner_mod

    with open(planner_mod.__file__, encoding="utf-8") as fh:
        source = fh.read()
    for token in ("$match", "$limit", "$group", "$lookup", "aggregation", "SELECT"):
        assert token not in source, f"dialect token {token!r} leaked into core planner"


def test_limit_not_extracted_from_year():
    plan = QueryPlanner().build(_ctx(intent="show users created in 2023"), None)
    assert plan.request.limit is None


def test_sort_picks_field_after_by():
    # 'status' is a schema field appearing before 'by'; 'revenue' after it.
    ctx = _ctx(intent="top status accounts by revenue")
    plan = QueryPlanner().build(ctx, None)
    assert plan.request.sort == {"revenue": -1}
