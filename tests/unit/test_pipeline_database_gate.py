from guardmcp.core.models.domain import Action, DecisionStatus
from guardmcp.core.pipeline import GuardPipeline
from guardmcp.core.policy.engine import PolicyEngine
from guardmcp.core.policy.models import CollectionPolicy, DatabaseScope, Policy
from guardmcp.core.risk.engine import RiskEngine


class _Loader:
    def __init__(self, policy):
        self._p = policy
    def get(self, agent):
        return self._p


def _pipeline(policy):
    return GuardPipeline(
        policy_loader=_Loader(policy), policy_engine=PolicyEngine(), risk_engine=RiskEngine(),
        audit_logger=None, approval_store=None, executor=None,
    )


def test_disallowed_database_denied():
    p = Policy(agent="claude", databases_allow=["db1"],
               databases={"db1": DatabaseScope(collections=CollectionPolicy(allow=["x"]))})
    res = _pipeline(p).evaluate("claude", "x", Action.FIND, {}, database="db2")
    assert res.decision.status == DecisionStatus.DENIED
    assert res.decision.code == "DATABASE_NOT_ALLOWED"


def test_allowed_database_resolves_scope():
    p = Policy(agent="claude", databases_allow=["db1"],
               databases={"db1": DatabaseScope(collections=CollectionPolicy(allow=["x"]))})
    res = _pipeline(p).evaluate("claude", "x", Action.FIND, {}, database="db1")
    assert res.decision.status == DecisionStatus.ALLOWED
    assert res.request.database == "db1"


def test_none_database_backcompat():
    p = Policy(agent="claude", collections=CollectionPolicy(allow=["x"]))
    res = _pipeline(p).evaluate("claude", "x", Action.FIND, {})
    assert res.decision.status == DecisionStatus.ALLOWED
    assert res.request.database is None
