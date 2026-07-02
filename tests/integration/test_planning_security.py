# tests/integration/test_planning_security.py
import pytest

from guardmcp.core.interfaces.cost import CostEstimate, CostLevel
from guardmcp.core.models.domain import Action, Decision, DecisionStatus, Request
from guardmcp.core.pipeline import EvalResult
from guardmcp.core.planning.ambiguity import AmbiguityDetector
from guardmcp.core.planning.pipeline import PlanningPipeline
from guardmcp.core.planning.relationships import RelationshipResolver

ALLOWED = {"user", "project"}
DENIED = {"secrets"}


class _Executor:
    async def collection_indexes(self, collection):
        return []


class _Plugin:
    def __init__(self):
        self._executor = _Executor()
    async def relationships(self, resources):
        # Maliciously report an edge to a denied collection.
        return [{"from_resource": "user", "from_field": "secret_id", "to_resource": "secrets",
                 "to_field": "_id", "kind": "naming", "confidence": 0.5, "evidence": "x"}]
    async def estimate(self, req):
        return CostEstimate(estimated_cost=CostLevel.LOW)


class _GovGuard:
    """Mimics governed accessors: only ALLOWED collections, masked field hidden."""
    async def discover_collections(self, agent):
        return sorted(ALLOWED)
    async def describe_collection(self, agent, collection):
        if collection not in ALLOWED:
            return None
        # 'is_active' is masked → excluded from schema by the real accessor.
        # Only 'status' (another concept-"active" candidate) is visible.
        return {"fields": {"status": "string"}}
    def evaluate_capability(self, agent, resource, capability, request=None):
        status = DecisionStatus.DENIED if resource in DENIED else DecisionStatus.ALLOWED
        return EvalResult(
            request=Request(agent=agent, collection=resource, action=Action.FIND, params={}),
            decision=Decision(status=status, reason="policy"),
            policy=None,
        )


class _DeniedGovGuard(_GovGuard):
    """Like _GovGuard but evaluate_capability always returns DENIED."""
    def evaluate_capability(self, agent, resource, capability, request=None):
        return EvalResult(
            request=Request(agent=agent, collection=resource, action=Action.FIND, params={}),
            decision=Decision(status=DecisionStatus.DENIED, reason="policy"),
            policy=None,
        )


def _pipeline():
    plugin = _Plugin()
    return PlanningPipeline(_GovGuard(), RelationshipResolver(lambda: plugin), lambda: plugin)


def _denied_pipeline():
    plugin = _Plugin()
    return PlanningPipeline(_DeniedGovGuard(), RelationshipResolver(lambda: plugin), lambda: plugin)


@pytest.mark.asyncio
async def test_denied_collection_never_in_relationships():
    g = await _pipeline().relationships("claude")
    assert "secrets" not in g.nodes
    assert all(e.to_resource != "secrets" for e in g.edges)


@pytest.mark.asyncio
async def test_masked_field_not_in_interpretations():
    """
    Invariant 2: a field masked (hidden) from the governed schema must not appear as
    an ambiguity interpretation in the pipeline result.

    The masked field is 'is_active', a concrete candidate for the concept "active" in
    _CONCEPTS.  The governed describe_collection only returns 'status' (another "active"
    candidate), so 'is_active' is absent from the schema → the detector cannot surface it.

    Control (Assertion B): calling AmbiguityDetector directly with a schema that INCLUDES
    'is_active' confirms it WOULD be returned — proving omission from describe_collection
    is the only reason it is absent from the pipeline result.
    """
    MASKED_FIELD = "is_active"
    VISIBLE_FIELD = "status"

    # Assertion A: masked field is absent from pipeline interpretations
    res = await _pipeline().plan("claude", "show active users")
    fields = {i.field for i in res.ambiguity.interpretations}
    assert MASKED_FIELD not in fields, (
        f"Masked field '{MASKED_FIELD}' must not surface as an interpretation "
        f"because the governed schema hides it; got fields={fields}"
    )

    # Assertion B (non-vacuous control): the detector WOULD return the masked field
    # when the schema explicitly includes it — proving the pipeline result's absence
    # is due to masking, not a detector bug.
    detector = AmbiguityDetector()
    direct_report = detector.detect(
        "show active users",
        {VISIBLE_FIELD: "string", MASKED_FIELD: "bool"},
        set(),
    )
    direct_fields = {i.field for i in direct_report.interpretations}
    assert MASKED_FIELD in direct_fields, (
        f"Control failed: AmbiguityDetector should return '{MASKED_FIELD}' when it is "
        f"present in the schema, but got fields={direct_fields}"
    )


@pytest.mark.asyncio
async def test_intent_naming_denied_collection_falls_back():
    """Invariant 3: requesting a denied collection must still yield a recommendation
    from an allowed collection (no conditional guard)."""
    res = await _pipeline().plan("claude", "read secrets", resource="secrets")
    # Must always produce a recommendation — a missing one is a real bug.
    assert res.recommended_plan is not None, (
        "Expected a fallback recommendation from an allowed collection, got None"
    )
    assert res.recommended_plan.request.resource in ALLOWED
    assert any("not authorized" in n.lower() for n in res.notes)


@pytest.mark.asyncio
async def test_plan_governance_allowed_matches_evaluate():
    """Invariant 4 (allowed branch): governance dict in each plan mirrors the guard's
    evaluate_capability return value."""
    guard = _GovGuard()
    res = await _pipeline().plan("claude", "show active users")
    for p in res.plans:
        ev = guard.evaluate_capability("claude", p.request.resource, p.request.capability)
        expected = ev.decision.status.value
        assert p.governance["decision"] == expected, (
            f"Plan governance {p.governance['decision']!r} != guard decision {expected!r}"
        )


@pytest.mark.asyncio
async def test_plan_governance_denied_matches_evaluate():
    """Invariant 4 (denied branch): when evaluate_capability returns DENIED for every
    resource, all plan governance dicts must reflect 'denied' and recommended_plan must
    be None (no plan passes the filter)."""
    guard = _DeniedGovGuard()
    res = await _denied_pipeline().plan("claude", "show active users")

    assert res.plans, "Expected at least one plan to be generated before governance"
    for p in res.plans:
        ev = guard.evaluate_capability("claude", p.request.resource, p.request.capability)
        expected = ev.decision.status.value  # "denied"
        assert p.governance["decision"] == expected, (
            f"Plan governance {p.governance['decision']!r} != guard decision {expected!r}"
        )

    # When all plans are denied, recommended_plan must be None.
    assert res.recommended_plan is None, (
        "recommended_plan should be None when all plans are denied by policy"
    )
