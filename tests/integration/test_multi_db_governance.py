# tests/integration/test_multi_db_governance.py
"""
Multi-database governance back-compat + adversarial integration tests.
Proves:
  1. A collection allowed in DB-A is denied against DB-B.
  2. Masked fields resolve independently per database.
  3. An unlisted database is gated at the pipeline with DATABASE_NOT_ALLOWED.
  4. A flat (no-databases) policy behaves identically with and without database=None.
"""
from guardmcp.core.models.domain import Action, DecisionStatus, Request, RiskLevel
from guardmcp.core.pipeline import GuardPipeline
from guardmcp.core.policy.engine import PolicyEngine
from guardmcp.core.policy.models import CollectionPolicy, DatabaseScope, Policy
from guardmcp.core.risk.engine import RiskEngine

# ---------------------------------------------------------------------------
# Fixtures (reused from Task-3 unit test pattern)
# ---------------------------------------------------------------------------

E = PolicyEngine()


def _req(collection):
    return Request(agent="claude", collection=collection, action=Action.FIND, params={})


class _Loader:
    def __init__(self, policy):
        self._p = policy

    def get(self, agent):
        return self._p


def _pipeline(policy):
    return GuardPipeline(
        policy_loader=_Loader(policy),
        policy_engine=PolicyEngine(),
        risk_engine=RiskEngine(),
        audit_logger=None,
        approval_store=None,
        executor=None,
    )


# ---------------------------------------------------------------------------
# Brief-specified tests (verbatim)
# ---------------------------------------------------------------------------

def test_masking_independent_per_database():
    p = Policy(
        agent="claude",
        databases_allow=["a", "b"],
        databases={
            "a": DatabaseScope(collections=CollectionPolicy(allow=["*"]), mask_fields=["ssn"]),
            "b": DatabaseScope(collections=CollectionPolicy(allow=["*"]), mask_fields=["email"]),
        },
    )
    assert p.mask_fields_for("user", database="a") == ["ssn"]
    assert p.mask_fields_for("user", database="b") == ["email"]


def test_flat_policy_identical_with_none_database():
    p = Policy(agent="claude", collections=CollectionPolicy(allow=["user"]), mask_fields=["email"])
    assert p.scope_for(None).collections.allow == p.collections.allow
    assert p.mask_fields_for("user") == p.mask_fields_for("user", database=None) == ["email"]
    assert p.database_permitted("whatever") is True


# ---------------------------------------------------------------------------
# Engine-level adversarial cases
# ---------------------------------------------------------------------------

def test_engine_collection_allowed_db1_denied_db2():
    """Collection x allowed only in db1; same request targeting db2 is denied."""
    p = Policy(
        agent="claude",
        databases_allow=["db1", "db2"],
        databases={
            "db1": DatabaseScope(collections=CollectionPolicy(allow=["x"])),
            "db2": DatabaseScope(collections=CollectionPolicy(allow=["y"])),
        },
    )
    assert E.evaluate(_req("x"), p, RiskLevel.LOW, database="db1").status == DecisionStatus.ALLOWED
    assert E.evaluate(_req("x"), p, RiskLevel.LOW, database="db2").status == DecisionStatus.DENIED


# ---------------------------------------------------------------------------
# Pipeline-level adversarial: unlisted database returns DATABASE_NOT_ALLOWED
# ---------------------------------------------------------------------------

def test_pipeline_unlisted_database_returns_database_not_allowed():
    """An unlisted database (db3) is gated before collection check.

    The decision code must be DATABASE_NOT_ALLOWED.
    """
    p = Policy(
        agent="claude",
        databases_allow=["db1"],
        databases={"db1": DatabaseScope(collections=CollectionPolicy(allow=["x"]))},
    )
    res = _pipeline(p).evaluate("claude", "x", Action.FIND, {}, database="db3")
    assert res.decision.status == DecisionStatus.DENIED
    assert res.decision.code == "DATABASE_NOT_ALLOWED"
