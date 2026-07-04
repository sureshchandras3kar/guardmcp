# tests/integration/test_multi_db_phase2.py
"""
Phase 2 multi-database integration tests.

Proves:
  1. run() denies a database not in databases_allow on the EXECUTE path and
     never calls the executor (DATABASE_NOT_ALLOWED).
  2. An allowed database threads through to the executor.
  3. Result masking uses the TARGET database's mask set — a field masked in
     DB-A is redacted when reading that collection in DB-A, and a DIFFERENT
     field is masked in DB-B (independent, cross-database correctness).
  4. Back-compat: single-DB (database=None) results/masking identical to
     pre-Phase-2 behaviour.
"""
import pytest

from guardmcp.core.masking.masker import MASK_VALUE
from guardmcp.core.models.domain import Action
from guardmcp.core.pipeline import GuardPipeline
from guardmcp.core.policy.engine import PolicyEngine
from guardmcp.core.policy.models import CollectionPolicy, DatabaseScope, Policy
from guardmcp.core.risk.engine import RiskEngine

# ── helpers ──────────────────────────────────────────────────────────────────


class _Loader:
    def __init__(self, p):
        self._p = p

    def get(self, agent):
        return self._p


class _Executor:
    def __init__(self):
        self.calls = []

    async def execute(self, collection, action, params, database=None):
        self.calls.append((collection, database))
        return {
            "documents": [
                {"_id": 1, "email": "a@b.com", "ssn": "111", "name": "n"}
            ],
            "count": 1,
        }

    async def list_collections(self):
        return ["user"]


class _Audit:
    def build(self, **k):
        return k

    async def log(self, r):
        return None


def _pipeline(p, ex):
    return GuardPipeline(
        policy_loader=_Loader(p),
        policy_engine=PolicyEngine(),
        risk_engine=RiskEngine(),
        audit_logger=_Audit(),
        approval_store=None,
        executor=ex,
    )


def _multidb_policy():
    """Two databases, each masking a DIFFERENT field on the same collection."""
    return Policy(
        agent="claude",
        databases_allow=["a", "b"],
        databases={
            "a": DatabaseScope(
                collections=CollectionPolicy(allow=["user"]),
                mask_fields=["ssn"],
            ),
            "b": DatabaseScope(
                collections=CollectionPolicy(allow=["user"]),
                mask_fields=["email"],
            ),
        },
    )


# ── Test 1: execute-path gate denies unlisted DB, never calls executor ────────


@pytest.mark.asyncio
async def test_execute_path_gate_denies_unlisted_db():
    ex = _Executor()
    res = await _pipeline(_multidb_policy(), ex).run(
        "claude", "user", Action.FIND, {"filter": {}}, database="c"
    )
    assert res["status"] == "denied"
    assert res["code"] == "DATABASE_NOT_ALLOWED"
    # executor MUST NOT have been called
    assert ex.calls == []


# ── Test 2: allowed database threads through to the executor ──────────────────


@pytest.mark.asyncio
async def test_allowed_db_reaches_executor():
    ex = _Executor()
    res = await _pipeline(_multidb_policy(), ex).run(
        "claude", "user", Action.FIND, {"filter": {}}, database="a"
    )
    assert res["status"] == "success"
    assert ex.calls == [("user", "a")]


# ── Test 3: per-database masking (cross-DB independence) ─────────────────────


@pytest.mark.asyncio
async def test_masking_uses_target_database_maskset():
    # DB 'a': ssn masked, email visible
    ex_a = _Executor()
    res_a = await _pipeline(_multidb_policy(), ex_a).run(
        "claude", "user", Action.FIND, {"filter": {}}, database="a"
    )
    assert res_a["status"] == "success"
    docs_a = res_a["data"]["documents"][0]
    assert docs_a.get("ssn") == MASK_VALUE      # ssn IS masked in db 'a'
    assert docs_a.get("email") == "a@b.com"     # email NOT masked in db 'a'

    # DB 'b': email masked, ssn visible
    ex_b = _Executor()
    res_b = await _pipeline(_multidb_policy(), ex_b).run(
        "claude", "user", Action.FIND, {"filter": {}}, database="b"
    )
    assert res_b["status"] == "success"
    docs_b = res_b["data"]["documents"][0]
    assert docs_b.get("email") == MASK_VALUE    # email IS masked in db 'b'
    assert docs_b.get("ssn") == "111"           # ssn NOT masked in db 'b'


# ── Test 4: back-compat — database=None (single-DB) path unchanged ───────────


@pytest.mark.asyncio
async def test_single_db_backcompat_database_none():
    """
    A single-database policy (no databases_allow / no databases scope) with
    database=None must continue to work identically to pre-Phase-2 behaviour:
    allow the request and apply the flat mask_fields list.
    """
    single_db_policy = Policy(
        agent="claude",
        collections=CollectionPolicy(allow=["user"]),
        mask_fields=["ssn"],
    )
    ex = _Executor()
    res = await _pipeline(single_db_policy, ex).run(
        "claude", "user", Action.FIND, {"filter": {}}, database=None
    )
    assert res["status"] == "success"
    docs = res["data"]["documents"][0]
    assert docs.get("ssn") == MASK_VALUE    # ssn masked via flat policy
    assert docs.get("email") == "a@b.com"  # email NOT masked
