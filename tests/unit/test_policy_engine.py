from guardmcp.core.models.domain import Action, DecisionStatus, Request, RiskLevel
from guardmcp.core.policy.engine import PolicyEngine
from guardmcp.core.policy.models import (
    ActionPolicy,
    ApprovalPolicy,
    CollectionPolicy,
    Policy,
)


def _policy(**kwargs) -> Policy:
    defaults = dict(
        agent="test",
        mode="readonly",
        collections=CollectionPolicy(allow=["customers"], deny=["payroll"]),
        actions=ActionPolicy(allow=["find", "count", "aggregate"]),
        mask_fields=[],
        approval=ApprovalPolicy(high=False, critical=False),
    )
    defaults.update(kwargs)
    return Policy(**defaults)


def _request(action: Action, collection: str = "customers") -> Request:
    return Request(agent="test", collection=collection, action=action, params={})


engine = PolicyEngine()


class TestReadonlyMode:
    def test_find_allowed(self):
        d = engine.evaluate(_request(Action.FIND), _policy(), RiskLevel.LOW)
        assert d.status == DecisionStatus.ALLOWED

    def test_insert_blocked_in_readonly(self):
        d = engine.evaluate(_request(Action.INSERT_ONE), _policy(), RiskLevel.MEDIUM)
        assert d.status == DecisionStatus.DENIED
        assert "readonly" in d.reason

    def test_delete_blocked_in_readonly(self):
        d = engine.evaluate(_request(Action.DELETE_MANY), _policy(), RiskLevel.CRITICAL)
        assert d.status == DecisionStatus.DENIED

    def test_write_allowed_in_readwrite(self):
        # Empty actions.allow means all actions permitted (no allowlist restriction)
        p = _policy(mode="readwrite", actions=ActionPolicy(allow=[], deny=[]))
        d = engine.evaluate(_request(Action.INSERT_ONE), p, RiskLevel.MEDIUM)
        assert d.status == DecisionStatus.ALLOWED


class TestCollectionPermissions:
    def test_denied_collection_rejected(self):
        d = engine.evaluate(_request(Action.FIND, "payroll"), _policy(), RiskLevel.LOW)
        assert d.status == DecisionStatus.DENIED
        assert "payroll" in d.reason

    def test_not_in_allow_list(self):
        d = engine.evaluate(_request(Action.FIND, "inventory"), _policy(), RiskLevel.LOW)
        assert d.status == DecisionStatus.DENIED
        assert "allowed" in d.reason.lower()

    def test_allowed_collection_passes(self):
        d = engine.evaluate(_request(Action.FIND, "customers"), _policy(), RiskLevel.LOW)
        assert d.status == DecisionStatus.ALLOWED


class TestActionPermissions:
    def test_denied_action_rejected(self):
        p = _policy(actions=ActionPolicy(deny=["aggregate"]))
        d = engine.evaluate(_request(Action.AGGREGATE), p, RiskLevel.MEDIUM)
        assert d.status == DecisionStatus.DENIED
        assert "aggregate" in d.reason

    def test_not_in_allow_list(self):
        p = _policy(actions=ActionPolicy(allow=["find"]))
        d = engine.evaluate(_request(Action.COUNT), p, RiskLevel.LOW)
        assert d.status == DecisionStatus.DENIED

    def test_reason_includes_allowed_list(self):
        p = _policy(actions=ActionPolicy(allow=["find"]))
        d = engine.evaluate(_request(Action.COUNT), p, RiskLevel.LOW)
        assert "find" in d.reason


class TestApprovalGates:
    # Use empty action allow-list so write actions are not blocked before the approval gate
    _rw = dict(mode="readwrite", actions=ActionPolicy(allow=[], deny=[]))

    def test_critical_triggers_approval(self):
        p = _policy(**self._rw, approval=ApprovalPolicy(high=True, critical=True))
        d = engine.evaluate(_request(Action.DELETE_MANY), p, RiskLevel.CRITICAL)
        assert d.status == DecisionStatus.APPROVAL_REQUIRED
        assert "CRITICAL" in d.reason

    def test_high_triggers_approval(self):
        p = _policy(**self._rw, approval=ApprovalPolicy(high=True, critical=False))
        d = engine.evaluate(_request(Action.UPDATE_MANY), p, RiskLevel.HIGH)
        assert d.status == DecisionStatus.APPROVAL_REQUIRED

    def test_no_approval_gate_allows(self):
        p = _policy(**self._rw, approval=ApprovalPolicy(high=False, critical=False))
        d = engine.evaluate(_request(Action.UPDATE_ONE), p, RiskLevel.HIGH)
        assert d.status == DecisionStatus.ALLOWED


class TestDecisionCodes:
    """#9: every DENIED decision carries the canonical ErrorCode value."""

    _rw = dict(mode="readwrite")

    def test_readonly_denial_code(self):
        d = engine.evaluate(_request(Action.INSERT_ONE), _policy(), RiskLevel.MEDIUM)
        assert d.status == DecisionStatus.DENIED
        assert d.code == "READONLY"

    def test_collection_deny_code(self):
        p = _policy(**self._rw)
        d = engine.evaluate(_request(Action.FIND, collection="payroll"), p, RiskLevel.LOW)
        assert d.status == DecisionStatus.DENIED
        assert d.code == "COLLECTION_NOT_ALLOWED"

    def test_collection_not_in_allow_code(self):
        p = _policy(**self._rw)
        d = engine.evaluate(_request(Action.FIND, collection="orders"), p, RiskLevel.LOW)
        assert d.status == DecisionStatus.DENIED
        assert d.code == "COLLECTION_NOT_ALLOWED"

    def test_action_deny_code(self):
        p = _policy(**self._rw, actions=ActionPolicy(deny=["find"]))
        d = engine.evaluate(_request(Action.FIND), p, RiskLevel.LOW)
        assert d.status == DecisionStatus.DENIED
        assert d.code == "ACTION_NOT_ALLOWED"

    def test_action_not_in_allow_code(self):
        p = _policy(**self._rw, actions=ActionPolicy(allow=["count"]))
        d = engine.evaluate(_request(Action.FIND), p, RiskLevel.LOW)
        assert d.status == DecisionStatus.DENIED
        assert d.code == "ACTION_NOT_ALLOWED"

    def test_allowed_has_no_code(self):
        d = engine.evaluate(_request(Action.FIND), _policy(), RiskLevel.LOW)
        assert d.status == DecisionStatus.ALLOWED
        assert d.code is None
