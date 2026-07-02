from guardmcp.core.interfaces.capability import Capability, CapabilityRequest
from guardmcp.core.planning.models import (
    AlternativePlan,
    AmbiguityReport,
    ExecutionPlan,
    Interpretation,
    PlannerResult,
    PlanningContext,
    Relationship,
    RelationshipGraph,
)


def test_relationship_graph_defaults():
    g = RelationshipGraph(nodes=["user", "project"], edges=[], generated_at="t")
    assert g.cached is False
    assert g.edges == []


def test_execution_plan_wraps_capability_request():
    req = CapabilityRequest(
        capability=Capability.READ, resource="user", filter={"status": "ACTIVE"}
    )
    plan = ExecutionPlan(strategy="index_scan", request=req)
    assert plan.request.resource == "user"
    assert plan.complexity == "unknown"
    assert plan.limitations == []


def test_alternative_plan_extends_execution_plan():
    req = CapabilityRequest(capability=Capability.READ, resource="user")
    alt = AlternativePlan(strategy="collscan", request=req, rank=1, tradeoff="no index")
    assert isinstance(alt, ExecutionPlan)
    assert alt.rank == 1


def test_planner_result_defaults():
    amb = AmbiguityReport(ambiguous=False, confidence=1.0, interpretations=[], recommendation="")
    g = RelationshipGraph(nodes=[], edges=[], generated_at="t")
    res = PlannerResult(ambiguity=amb, relationships=g)
    assert res.plans == []
    assert res.recommended_plan is None
    assert res.notes == []


def test_planning_context_holds_authorized_only():
    g = RelationshipGraph(nodes=[], edges=[], generated_at="t")
    ctx = PlanningContext(
        agent="claude", intent="show active users", resource="user",
        allowed_resources=["user"], resource_schema={"fields": {}}, indexes=[], relationships=g,
    )
    assert ctx.allowed_resources == ["user"]


def test_relationship_construction():
    r = Relationship(from_resource="project", from_field="user_id", to_resource="user",
                     to_field="_id", kind="naming", confidence=0.5, evidence="naming match")
    assert r.kind == "naming"
    assert r.confidence == 0.5


def test_interpretation_construction():
    i = Interpretation(field="status", operator="=", value="ACTIVE", confidence=0.6, evidence="x")
    assert i.field == "status"
    assert i.value == "ACTIVE"
