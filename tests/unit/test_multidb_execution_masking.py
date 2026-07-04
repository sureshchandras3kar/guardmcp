# tests/unit/test_multidb_execution_masking.py
"""
Phase 2 multi-database governance: database reaches EXECUTION + result masking.

Proves the two cross-database correctness hazards are closed:
  1. Policy.result_transformer / audit_masker cache + resolve per (collection,
     database) — a field masked in DB-A is NOT returned unmasked when the same
     collection name is read in DB-B, and vice versa.
  2. GuardPipeline._guard_aggregation resolves $lookup foreign-collection
     permission and masked-field references against the PER-DATABASE scope, not
     the flat policy — an aggregation in DB-A cannot reach a collection or
     masked field governed differently in DB-B.
"""
from guardmcp.core.masking.masker import MASK_VALUE
from guardmcp.core.models.domain import Action, Request
from guardmcp.core.pipeline import GuardPipeline
from guardmcp.core.policy.engine import PolicyEngine
from guardmcp.core.policy.models import CollectionPolicy, DatabaseScope, Policy
from guardmcp.core.risk.engine import RiskEngine


class _Loader:
    def __init__(self, policy):
        self._p = policy

    def get(self, agent):
        return self._p


class _FakeAggExecutor:
    """Minimal pipeline-introspecting executor (mirrors the mongo plugin API)."""

    def referenced_collections(self, params):
        refs = set()
        for stage in params.get("pipeline", []):
            lk = stage.get("$lookup")
            if lk:
                refs.add(lk["from"])
        return refs

    def masked_field_references(self, params, mask_fields):
        found = set()
        for stage in params.get("pipeline", []):
            for key in stage.get("$match", {}):
                if key in mask_fields:
                    found.add(key)
        return found


def _pipeline(policy, executor=None):
    return GuardPipeline(
        policy_loader=_Loader(policy),
        policy_engine=PolicyEngine(),
        risk_engine=RiskEngine(),
        audit_logger=None,
        approval_store=None,
        executor=executor,
    )


def _two_db_policy():
    """Same collection name, different masked field per database."""
    return Policy(
        agent="claude",
        databases_allow=["a", "b"],
        databases={
            "a": DatabaseScope(collections=CollectionPolicy(allow=["*"]), mask_fields=["ssn"]),
            "b": DatabaseScope(collections=CollectionPolicy(allow=["*"]), mask_fields=["email"]),
        },
    )


# ── Hazard 1: cache re-keyed by (collection, database) ─────────────────────────

def test_result_transformer_rekeys_by_database():
    p = _two_db_policy()
    doc = {"ssn": "111", "email": "x@y.com"}
    out_a = p.result_transformer("user", database="a").transform_result([dict(doc)])[0]
    out_b = p.result_transformer("user", database="b").transform_result([dict(doc)])[0]
    assert out_a["ssn"] == MASK_VALUE and out_a["email"] == "x@y.com"
    assert out_b["email"] == MASK_VALUE and out_b["ssn"] == "111"


def test_audit_masker_rekeys_by_database():
    p = _two_db_policy()
    params = {"filter": {"ssn": "111", "email": "x@y.com"}}
    a = p.audit_masker("user", database="a").mask_result(params)
    b = p.audit_masker("user", database="b").mask_result(params)
    assert a["filter"]["ssn"] == MASK_VALUE and a["filter"]["email"] == "x@y.com"
    assert b["filter"]["email"] == MASK_VALUE and b["filter"]["ssn"] == "111"


# ── Hazard 1 at the execution boundary: _build_success is database-aware ───────

def test_build_success_masks_per_database():
    p = _two_db_policy()
    pipe = _pipeline(p)
    raw = {"documents": [{"ssn": "111", "email": "x@y.com"}]}
    da = pipe._build_success(raw, Action.FIND, p, "user", "a")["data"]["documents"][0]
    db = pipe._build_success(raw, Action.FIND, p, "user", "b")["data"]["documents"][0]
    assert da["ssn"] == MASK_VALUE and da["email"] == "x@y.com"
    assert db["email"] == MASK_VALUE and db["ssn"] == "111"


# ── Hazard 2: aggregation guard resolves against per-database scope ────────────

def test_guard_aggregation_foreign_collection_per_database():
    p = Policy(
        agent="claude",
        databases_allow=["a", "b"],
        databases={
            "a": DatabaseScope(collections=CollectionPolicy(allow=["users"])),
            "b": DatabaseScope(collections=CollectionPolicy(allow=["users", "orders"])),
        },
    )
    pipe = _pipeline(p, executor=_FakeAggExecutor())
    params = {"pipeline": [{"$lookup": {"from": "orders"}}]}
    req_a = Request(agent="claude", collection="users", action=Action.AGGREGATE,
                    params=params, database="a")
    req_b = Request(agent="claude", collection="users", action=Action.AGGREGATE,
                    params=params, database="b")
    # orders not permitted in a → denied; permitted in b → no objection.
    assert pipe._guard_aggregation(req_a, p) is not None
    assert pipe._guard_aggregation(req_b, p) is None


def test_guard_aggregation_masked_field_per_database():
    p = _two_db_policy()  # a masks ssn, b masks email; both allow "*"
    pipe = _pipeline(p, executor=_FakeAggExecutor())
    params = {"pipeline": [{"$match": {"ssn": "111"}}]}
    req_a = Request(agent="claude", collection="user", action=Action.AGGREGATE,
                    params=params, database="a")
    req_b = Request(agent="claude", collection="user", action=Action.AGGREGATE,
                    params=params, database="b")
    # ssn masked in a → referencing it in a pipeline is denied; not masked in b.
    assert pipe._guard_aggregation(req_a, p) is not None
    assert pipe._guard_aggregation(req_b, p) is None
