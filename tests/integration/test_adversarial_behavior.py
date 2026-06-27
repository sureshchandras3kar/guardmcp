"""
Adversarial / user-centric behavior tests (scenarios that the YAML eval
framework cannot express). Each test FIRST establishes the actual behavior via
the real code path, then asserts the secure outcome — except where a real
limitation/leak exists, which is documented with an explicit marker so the
behavior is locked and the finding is visible (see the session report).

Scenarios covered here:
  EC-3  masking depth-limit leak               (FINDING: real leak)
  SEC-3 explain does not leak masked literals   (SECURE — locked)
  ADV-7 sort on masked field                    (values masked; order = known limitation)
  REL-5 approval timeout -> deny + audit         (SECURE — locked)
  CR-2  discovery / switch are audited           (SECURE — locked)
  AG-5/PD-4 unsupported capability               (SECURE — locked)
  FT-6  missing filter on write != match-all     (SECURE — risk escalates to CRITICAL)
  MCP-3/4 wrong-type / bad-JSON param -> VALIDATION (SECURE — locked)
"""

import json
import tempfile
from pathlib import Path

import pytest
from mongomock_motor import AsyncMongoMockClient
from pydantic import TypeAdapter, ValidationError

from guardmcp.core.approval.store import ApprovalStore
from guardmcp.core.audit.logger import AuditLogger
from guardmcp.core.interfaces.capability import ACTION_TO_CAPABILITY, Capability
from guardmcp.core.masking.masker import _MAX_DEPTH, MASK_VALUE, FieldMasker, ResultTransformer
from guardmcp.core.models.domain import Action, DecisionStatus, RiskLevel
from guardmcp.core.pipeline import GuardPipeline
from guardmcp.core.policy.engine import PolicyEngine
from guardmcp.core.policy.models import CollectionPolicy, Policy
from guardmcp.core.risk.engine import RiskEngine
from guardmcp.core.validation import JsonDict
from guardmcp.plugins.mongodb.executor import MongoExecutor
from guardmcp.server.tools._common import _capability_check

# ── helpers ──────────────────────────────────────────────────────────────────


class _Loader:
    def __init__(self, policy: Policy) -> None:
        self._p = policy

    def get(self, agent: str):
        return self._p if agent == self._p.agent else None


def _mock_client(mongo: AsyncMongoMockClient, db: str = "testdb"):
    class _C:
        def get_collection(self, name):
            return mongo[db][name]

        def get_db(self):
            return mongo[db]

        async def list_collection_names(self):
            return await mongo[db].list_collection_names()

        async def list_databases(self):
            return [{"name": db, "sizeOnDisk": 0}]

        def close(self):
            pass

    return _C()


def _build_pipeline(policy: Policy, mongo: AsyncMongoMockClient, *, approval_timeout=1.0):
    executor = MongoExecutor(_mock_client(mongo), schema_cache_ttl=0)
    tmp = Path(tempfile.mkdtemp())
    audit = AuditLogger(tmp / "audit.jsonl")
    pipeline = GuardPipeline(
        policy_loader=_Loader(policy),
        policy_engine=PolicyEngine(),
        risk_engine=RiskEngine(),
        audit_logger=audit,
        approval_store=ApprovalStore(timeout_seconds=approval_timeout),
        executor=executor,
    )
    return pipeline, audit


def _read_audit(audit: AuditLogger) -> list[dict]:
    path = audit._path
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _nest(depth: int, leaf: dict) -> dict:
    """Return a doc with `leaf` wrapped `depth` levels deep under key 'lvl'."""
    d = dict(leaf)
    for _ in range(depth):
        d = {"lvl": d}
    return d


def _descend(doc: dict) -> dict:
    cur = doc
    while isinstance(cur, dict) and "lvl" in cur:
        cur = cur["lvl"]
    return cur


# ── EC-3: masking depth-limit leak (FINDING) ──────────────────────────────────


def test_ec3_shallow_masked_field_is_masked():
    """Control: a masked field within the depth limit IS masked."""
    masker = FieldMasker(["ssn"])
    out = masker.mask(_nest(3, {"ssn": "111-22-3333"}))
    assert _descend(out)["ssn"] == MASK_VALUE


def test_ec3_deep_masked_field_is_masked_fieldmasker():
    """EC-3 FIXED: a masked field nested at depth 12 (was > old _MAX_DEPTH==10)
    is now masked, not leaked in clear-text."""
    masker = FieldMasker(["ssn"])
    out = masker.mask(_nest(12, {"ssn": "SECRET-DEEP"}))
    assert _descend(out)["ssn"] == MASK_VALUE


def test_ec3_deep_masked_field_is_masked_transformer():
    """EC-3 FIXED: same, via the ResultTransformer (find/aggregate path)."""
    t = ResultTransformer(["ssn"], [])
    out = t.transform_result(_nest(12, {"ssn": "SECRET-DEEP"}))
    assert _descend(out)["ssn"] == MASK_VALUE


def test_ec3_secure_no_cleartext_at_depth_12():
    """EC-3 evidence (now SECURE): the deep ssn never comes back in clear-text."""
    assert _MAX_DEPTH >= 12
    masker = FieldMasker(["ssn"])
    out = masker.mask(_nest(12, {"ssn": "SECRET-DEEP"}))
    assert _descend(out)["ssn"] == MASK_VALUE
    assert "SECRET-DEEP" not in repr(out)


def test_ec3_beyond_bound_redacts_not_raw():
    """EC-3 fail-safe: a masked field nested far beyond _MAX_DEPTH must NOT be
    returned raw. The over-deep subtree is redacted to a sentinel instead."""
    from guardmcp.core.masking.masker import _DEPTH_REDACTION

    masker = FieldMasker(["ssn"])
    out = masker.mask(_nest(30, {"ssn": "SECRET-DEEP"}))
    # No cleartext leaks anywhere in the returned structure.
    assert "SECRET-DEEP" not in repr(out)
    # The over-deep subtree is the redaction sentinel.
    cur = out
    while isinstance(cur, dict) and "lvl" in cur:
        cur = cur["lvl"]
    assert cur == _DEPTH_REDACTION

    t = ResultTransformer(["ssn"], [])
    out2 = t.transform_result(_nest(30, {"ssn": "SECRET-DEEP"}))
    assert "SECRET-DEEP" not in repr(out2)


# ── SEC-3: explain does not leak masked literals (SECURE) ──────────────────────


def test_sec3_explain_plan_masks_filter_literal():
    """db_explain output is run through the audit masker (S-1). A masked field's
    literal echoed in the query plan under the masked KEY is redacted."""
    policy = Policy(
        agent="a",
        mode="readonly",
        collections=CollectionPolicy(allow=["customers"]),
        mask_fields=["ssn"],
    )
    plan = {
        "queryPlanner": {
            "parsedQuery": {"ssn": {"$eq": "111-22-3333"}},
            "winningPlan": {"filter": {"ssn": "111-22-3333"}},
        }
    }
    gp = GuardPipeline.__new__(GuardPipeline)
    out = gp._build_success(plan, Action.EXPLAIN, policy, "customers")
    blob = json.dumps(out["data"])
    assert "111-22-3333" not in blob
    assert out["data"]["queryPlanner"]["parsedQuery"]["ssn"] == MASK_VALUE
    assert out["data"]["queryPlanner"]["winningPlan"]["filter"]["ssn"] == MASK_VALUE


# ── ADV-7: sort on masked field (values masked; order = known limitation) ──────


@pytest.mark.asyncio
async def test_adv7_sort_on_masked_field_masks_values():
    """Sorting by a masked field still returns the field MASKED. The relative
    ORDER of rows is an inherent oracle (KNOWN LIMITATION, see report ADV-7) —
    here we lock the security-relevant invariant: the values stay masked."""
    mongo = AsyncMongoMockClient()
    await mongo["testdb"]["customers"].insert_many(
        [
            {"name": "Alice", "salary": 50000},
            {"name": "Bob", "salary": 90000},
            {"name": "Carol", "salary": 70000},
        ]
    )
    policy = Policy(
        agent="a",
        mode="readonly",
        collections=CollectionPolicy(allow=["customers"]),
        mask_fields=["salary"],
    )
    pipeline, audit = _build_pipeline(policy, mongo)
    res = await pipeline.run(
        "a", "customers", Action.FIND, {"filter": {}, "sort": {"salary": -1}, "limit": 10}
    )
    assert res["status"] == "success"
    docs = res["data"]["documents"]
    assert len(docs) == 3
    for d in docs:
        assert d["salary"] == MASK_VALUE  # value never exposed
    await audit.aclose()


# ── REL-5: approval timeout -> deny + audit (SECURE) ───────────────────────────


@pytest.mark.asyncio
async def test_rel5_approval_timeout_denies_and_audits():
    """A CRITICAL op that requires approval but never gets resolved times out and
    the pipeline returns a DENY with APPROVAL_DECLINED code, and audits it."""
    mongo = AsyncMongoMockClient()
    await mongo["testdb"]["customers"].insert_one({"name": "Alice"})
    policy = Policy(
        agent="a",
        mode="readwrite",
        collections=CollectionPolicy(allow=["customers"]),
        approval={"high": True, "critical": True},
    )
    # tiny timeout so wait_for_decision returns "denied" with no resolution
    pipeline, audit = _build_pipeline(policy, mongo, approval_timeout=0.05)

    res = await pipeline.run("a", "customers", Action.DELETE_MANY, {"filter": {}})
    assert res["status"] == "denied"
    from guardmcp.core.interfaces.errors import ErrorCode

    assert res["code"] == ErrorCode.APPROVAL_DECLINED.value

    records = _read_audit(audit)
    # final audit record for this op is a denial mentioning timeout
    final = [r for r in records if r["action"] == "delete_many" and r["status"] == "denied"]
    assert final, f"expected a denied audit record, got {records}"
    assert "tim" in (final[-1]["reason"] or "").lower()  # 'timed out'
    await audit.aclose()


# ── CR-2: discovery / describe / switch are audited (SECURE) ───────────────────


@pytest.mark.asyncio
async def test_cr2_discover_collections_is_audited():
    mongo = AsyncMongoMockClient()
    await mongo["testdb"]["customers"].insert_one({"x": 1})
    policy = Policy(agent="a", mode="readonly", collections=CollectionPolicy(allow=["customers"]))
    pipeline, audit = _build_pipeline(policy, mongo)
    await pipeline.discover_collections("a")
    recs = _read_audit(audit)
    assert any(r["action"] == "list_collections" for r in recs)
    await audit.aclose()


@pytest.mark.asyncio
async def test_cr2_describe_collection_is_audited():
    mongo = AsyncMongoMockClient()
    await mongo["testdb"]["customers"].insert_one({"x": 1})
    policy = Policy(agent="a", mode="readonly", collections=CollectionPolicy(allow=["customers"]))
    pipeline, audit = _build_pipeline(policy, mongo)
    await pipeline.describe_collection("a", "customers")
    recs = _read_audit(audit)
    assert any(r["action"] == "collection_schema" for r in recs)
    await audit.aclose()


@pytest.mark.asyncio
async def test_cr2_switch_connection_is_audited():
    mongo = AsyncMongoMockClient()
    policy = Policy(agent="a", mode="readonly", collections=CollectionPolicy(allow=["customers"]))
    pipeline, audit = _build_pipeline(policy, mongo)
    # no registry → switch returns False, but the attempt must still be audited
    ok = await pipeline.switch_connection_audited("a", "secondary")
    assert ok is False
    recs = _read_audit(audit)
    assert any(r["action"] == "switch_connection" for r in recs)
    await audit.aclose()


# ── AG-5 / PD-4: unsupported capability (SECURE) ───────────────────────────────


def test_ag5_unsupported_capability_returns_envelope():
    """A backend whose supported set excludes AGGREGATE makes _capability_check
    return an UNSUPPORTED_CAPABILITY error envelope instead of executing."""

    class _Plugin:
        name = "limited-sql"
        supported = frozenset({Capability.READ, Capability.COUNT})

    class _Entry:
        plugin = _Plugin()

    class _Registry:
        def get_active(self):
            return _Entry()

    class _Pipe:
        _registry = _Registry()

    assert ACTION_TO_CAPABILITY[Action.AGGREGATE] == Capability.AGGREGATE
    out = _capability_check(_Pipe(), Action.AGGREGATE)
    assert out is not None
    parsed = json.loads(out)
    assert parsed["ok"] is False
    assert parsed["error"]["code"] == "UNSUPPORTED_CAPABILITY"
    assert "aggregate" in parsed["error"]["message"]
    # a SUPPORTED capability passes the check (None == no objection)
    assert _capability_check(_Pipe(), Action.COUNT) is None


# ── FT-6: missing filter on write != match-all (SECURE) ────────────────────────


def test_ft6_empty_filter_delete_escalates_to_critical():
    """An empty/missing filter on a mutation escalates risk to CRITICAL (S-4),
    so it cannot silently match-all without hitting the CRITICAL approval gate."""
    risk = RiskEngine()
    assert risk.classify(Action.DELETE_ONE, {"filter": {}}) == RiskLevel.CRITICAL
    assert risk.classify(Action.DELETE_MANY, {"filter": {}}) == RiskLevel.CRITICAL
    assert risk.classify(Action.UPDATE_ONE, {}) == RiskLevel.CRITICAL
    # a scoped filter is the lower, non-escalated risk
    assert risk.classify(Action.DELETE_ONE, {"filter": {"_id": 1}}) == RiskLevel.HIGH


@pytest.mark.asyncio
async def test_ft6_empty_filter_delete_requires_approval_then_blocks():
    """End-to-end: empty-filter delete_one on a readwrite policy with critical
    approval enabled → APPROVAL_REQUIRED at evaluate time (a gate, not a silent
    collection-wide delete)."""
    mongo = AsyncMongoMockClient()
    await mongo["testdb"]["customers"].insert_many([{"x": 1}, {"x": 2}])
    policy = Policy(
        agent="a",
        mode="readwrite",
        collections=CollectionPolicy(allow=["customers"]),
        approval={"high": True, "critical": True},
    )
    pipeline, _ = _build_pipeline(policy, mongo)
    ev = pipeline.evaluate("a", "customers", Action.DELETE_ONE, {"filter": {}})
    assert ev.decision.status == DecisionStatus.APPROVAL_REQUIRED
    assert ev.decision.risk == RiskLevel.CRITICAL
    # nothing was deleted by merely evaluating
    assert await mongo["testdb"]["customers"].count_documents({}) == 2


# ── MCP-3/4: wrong-type / bad-JSON param -> VALIDATION (SECURE) ────────────────


def test_mcp34_jsondict_rejects_bad_json_string():
    ta = TypeAdapter(JsonDict)
    with pytest.raises(ValidationError):
        ta.validate_python("{not valid json}")


def test_mcp34_jsondict_rejects_wrong_type():
    ta = TypeAdapter(JsonDict)
    with pytest.raises(ValidationError):
        ta.validate_python(123)  # int is neither dict, None, nor JSON string


def test_mcp34_jsondict_accepts_valid_json_string_and_dict():
    ta = TypeAdapter(JsonDict)
    assert ta.validate_python('{"a": 1}') == {"a": 1}
    assert ta.validate_python({"b": 2}) == {"b": 2}
    # none-sentinels coerce to None (documented behavior)
    assert ta.validate_python("") is None
    assert ta.validate_python("null") is None
