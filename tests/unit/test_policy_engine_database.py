from guardmcp.core.models.domain import Action, DecisionStatus, Request, RiskLevel
from guardmcp.core.policy.engine import PolicyEngine
from guardmcp.core.policy.models import CollectionPolicy, DatabaseScope, Policy

E = PolicyEngine()


def _req(collection):
    return Request(agent="claude", collection=collection, action=Action.FIND, params={})


def test_none_database_uses_flat_collections():
    p = Policy(agent="claude", collections=CollectionPolicy(allow=["user"]))
    assert E.evaluate(_req("user"), p, RiskLevel.LOW).status == DecisionStatus.ALLOWED
    assert E.evaluate(_req("secret"), p, RiskLevel.LOW).status == DecisionStatus.DENIED


def test_collection_allowed_in_one_db_denied_in_another():
    p = Policy(agent="claude", databases_allow=["db1", "db2"],
               databases={"db1": DatabaseScope(collections=CollectionPolicy(allow=["x"])),
                          "db2": DatabaseScope(collections=CollectionPolicy(allow=["y"]))})
    assert E.evaluate(_req("x"), p, RiskLevel.LOW, database="db1").status == DecisionStatus.ALLOWED
    assert E.evaluate(_req("x"), p, RiskLevel.LOW, database="db2").status == DecisionStatus.DENIED
