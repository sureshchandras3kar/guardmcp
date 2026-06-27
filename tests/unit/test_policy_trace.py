"""
Tests for the single-source-of-truth evaluation trace.

Verifies the engine records the right TraceStep at each rule's existing decision
point, AND — critically — that the trace=None hot path produces an IDENTICAL
Decision (backward-compat / zero hot-path cost proof).
"""

from guardmcp.core.models.domain import (
    Action,
    DecisionStatus,
    Request,
    RiskLevel,
)
from guardmcp.core.policy.engine import PolicyEngine
from guardmcp.core.policy.models import (
    ActionPolicy,
    ApprovalPolicy,
    CollectionPolicy,
    Policy,
)
from guardmcp.core.policy.trace import PolicyTrace

engine = PolicyEngine()


def _policy(**kwargs) -> Policy:
    defaults = dict(
        agent="test",
        mode="readwrite",
        collections=CollectionPolicy(allow=["customers"]),
        actions=ActionPolicy(),
        approval=ApprovalPolicy(),
    )
    defaults.update(kwargs)
    return Policy(**defaults)


def _request(action: Action, collection: str = "customers") -> Request:
    return Request(agent="test", collection=collection, action=action, params={})


def _matched(trace: PolicyTrace) -> list[str]:
    return [s.rule for s in trace.steps if s.result == "matched"]


# ── Each rule records the right matched step ─────────────────────────────────


def test_readonly_deny_records_step():
    pol = _policy(mode="readonly")
    trace = PolicyTrace()
    d = engine.evaluate(_request(Action.INSERT_ONE), pol, RiskLevel.MEDIUM, trace=trace)
    assert d.status == DecisionStatus.DENIED
    assert "readonly_mode" in _matched(trace)


def test_collection_deny_records_step():
    pol = _policy(collections=CollectionPolicy(allow=["customers"], deny=["secrets"]))
    trace = PolicyTrace()
    d = engine.evaluate(
        _request(Action.FIND, collection="secrets"), pol, RiskLevel.LOW, trace=trace
    )
    assert d.status == DecisionStatus.DENIED
    assert "collection_access" in _matched(trace)


def test_action_deny_records_step():
    pol = _policy(actions=ActionPolicy(deny=["find"]))
    trace = PolicyTrace()
    d = engine.evaluate(_request(Action.FIND), pol, RiskLevel.LOW, trace=trace)
    assert d.status == DecisionStatus.DENIED
    assert "action_deny" in _matched(trace)


def test_allowed_records_default_allow():
    pol = _policy()
    trace = PolicyTrace()
    d = engine.evaluate(_request(Action.FIND), pol, RiskLevel.LOW, trace=trace)
    assert d.status == DecisionStatus.ALLOWED
    assert "default_allow" in _matched(trace)
    # Earlier rules should be recorded as passed.
    rules = {s.rule: s.result for s in trace.steps}
    assert rules["readonly_mode"] == "passed"
    assert rules["collection_access"] == "passed"


def test_approval_required_records_step():
    pol = _policy(approval=ApprovalPolicy(high=True))
    trace = PolicyTrace()
    d = engine.evaluate(_request(Action.UPDATE_ONE), pol, RiskLevel.HIGH, trace=trace)
    assert d.status == DecisionStatus.APPROVAL_REQUIRED
    assert "approval_high" in _matched(trace)


# ── Backward-compat: trace=None hot path is identical ────────────────────────


def test_trace_none_decision_identical():
    """Same Decision with and without a trace, across every rule outcome."""
    cases = [
        (_policy(mode="readonly"), Action.INSERT_ONE, RiskLevel.MEDIUM),
        (
            _policy(collections=CollectionPolicy(allow=["customers"], deny=["x"])),
            Action.FIND,
            RiskLevel.LOW,
        ),
        (_policy(actions=ActionPolicy(deny=["find"])), Action.FIND, RiskLevel.LOW),
        (_policy(actions=ActionPolicy(allow=["count"])), Action.FIND, RiskLevel.LOW),
        (_policy(approval=ApprovalPolicy(high=True)), Action.UPDATE_ONE, RiskLevel.HIGH),
        (_policy(approval=ApprovalPolicy(critical=True)), Action.DELETE_MANY, RiskLevel.CRITICAL),
        (_policy(), Action.FIND, RiskLevel.LOW),
    ]
    for pol, action, risk in cases:
        coll = "secrets" if "x" not in pol.collections.deny else "x"
        req = _request(action, collection="customers" if coll != "x" else "x")
        without = engine.evaluate(req, pol, risk)
        with_trace = engine.evaluate(req, pol, risk, trace=PolicyTrace())
        assert without.model_dump() == with_trace.model_dump(), (action, risk)
