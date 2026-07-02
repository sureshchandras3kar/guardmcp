import pytest

from guardmcp.core.interfaces.cost import CostEstimate, CostLevel
from guardmcp.core.models.domain import Action, Decision, DecisionStatus, Request
from guardmcp.core.pipeline import EvalResult
from guardmcp.core.planning.models import RelationshipGraph
from guardmcp.core.planning.pipeline import PlanningPipeline
from guardmcp.core.planning.relationships import RelationshipResolver


class _Guard:
    def __init__(self, allowed, fields, decision=DecisionStatus.ALLOWED):
        self._allowed = allowed
        self._fields = fields
        self._decision = decision

    async def discover_collections(self, agent):
        return list(self._allowed)

    async def describe_collection(self, agent, collection):
        return {"fields": self._fields}

    def evaluate_capability(self, agent, resource, capability, request=None):
        return EvalResult(
            request=Request(agent=agent, collection=resource, action=Action.FIND, params={}),
            decision=Decision(status=self._decision, reason="ok"),
            policy=None,
        )


class _Executor:
    async def collection_indexes(self, collection):
        return [{"name": "status_1", "key": [("status", 1)]}]


class _Plugin:
    def __init__(self):
        self._executor = _Executor()
    async def relationships(self, resources):
        return []
    async def estimate(self, req):
        return CostEstimate(estimated_cost=CostLevel.LOW, index_used=True)


def _pipeline(guard, plugin):
    return PlanningPipeline(guard, RelationshipResolver(lambda: plugin), lambda: plugin)


@pytest.mark.asyncio
async def test_plan_returns_ranked_plans_when_unambiguous():
    guard = _Guard(["user"], {"status": "string"})
    res = await _pipeline(guard, _Plugin()).plan("claude", "show active users")
    assert res.ambiguity.ambiguous is False
    assert res.recommended_plan is not None
    assert res.recommended_plan.request.filter == {"status": "ACTIVE"}
    assert res.recommended_plan.governance["decision"] == "allowed"
    assert res.recommended_plan.est_cost.estimated_cost == CostLevel.LOW


@pytest.mark.asyncio
async def test_plan_short_circuits_when_ambiguous():
    guard = _Guard(["user"], {"status": "string", "is_active": "bool"})
    res = await _pipeline(guard, _Plugin()).plan("claude", "show active users")
    assert res.ambiguity.ambiguous is True
    assert res.plans == []
    assert res.recommended_plan is None
    assert set(res.relationships.nodes) == {"user"}


@pytest.mark.asyncio
async def test_denied_plans_surfaced_but_not_recommended():
    from guardmcp.core.models.domain import DecisionStatus
    guard = _Guard(["user"], {"status": "string"}, decision=DecisionStatus.DENIED)
    res = await _pipeline(guard, _Plugin()).plan("claude", "show active users")
    assert res.plans, "denied plans must still be listed for transparency"
    assert all(p.governance["decision"] == "denied" for p in res.plans)
    assert res.recommended_plan is None
    assert any("denied" in n.lower() for n in res.notes)


@pytest.mark.asyncio
async def test_plan_degrades_with_no_allowed_collections():
    guard = _Guard([], {})
    res = await _pipeline(guard, _Plugin()).plan("claude", "show active users")
    assert res.plans == []
    assert any("authorized" in n.lower() for n in res.notes)


@pytest.mark.asyncio
async def test_relationships_uses_allowed_only():
    guard = _Guard(["user", "project"], {})
    g = await _pipeline(guard, _Plugin()).relationships("claude")
    assert isinstance(g, RelationshipGraph)
    assert set(g.nodes) == {"user", "project"}


@pytest.mark.asyncio
async def test_plural_intent_word_selects_singular_resource():
    guard = _Guard(["background_jobs_configuration", "user"], {"status": "string"})
    res = await _pipeline(guard, _Plugin()).plan("claude", "show active users")
    # must NOT fall back to the first collection; must pick 'user'
    assert res.recommended_plan is not None
    assert res.recommended_plan.request.resource == "user"
    assert not any("defaulted to" in n.lower() for n in res.notes)
