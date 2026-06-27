"""#1 seam: capability-native evaluate_capability() maps Capability -> a
representative Action and delegates to evaluate(). Action is NOT deleted; v2
will invert primacy."""

import pytest

from guardmcp.core.interfaces.capability import Capability, CapabilityRequest
from guardmcp.core.models.domain import Action, DecisionStatus


@pytest.mark.asyncio
async def test_evaluate_capability_allows_read(pipeline):
    res = pipeline.evaluate_capability("test-agent", "customers", Capability.READ)
    assert res.request.action == Action.FIND
    assert res.decision.status == DecisionStatus.ALLOWED


@pytest.mark.asyncio
async def test_evaluate_capability_denies_forbidden_collection(pipeline):
    res = pipeline.evaluate_capability("test-agent", "payroll", Capability.READ)
    assert res.decision.status == DecisionStatus.DENIED


@pytest.mark.asyncio
async def test_evaluate_capability_uses_request_action(pipeline):
    # WRITE_ONE is ambiguous; req.action pins the concrete operation.
    req = CapabilityRequest(
        capability=Capability.WRITE_ONE,
        resource="customers",
        action="update_one",
        update={"$set": {"x": 1}},
    )
    res = pipeline.evaluate_capability("test-agent", "customers", Capability.WRITE_ONE, req)
    assert res.request.action == Action.UPDATE_ONE
    # readonly policy → denied, but the Action mapping is what we assert here.
    assert res.decision.status == DecisionStatus.DENIED
