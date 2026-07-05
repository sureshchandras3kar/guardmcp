"""Integration tests: field-semantics (Context Engine slice 1).

Proves four guarantees:
  1. Data-agnostic structural detection with product-neutral field names.
  2. Masked field never carries a value in semantics (role=pii, values=None).
  3. End-to-end via describe_collection: semantics + masked_fields in output.
  4. Governance: denied collection → None; masked field never valued end-to-end.
"""
from __future__ import annotations

import pytest

from guardmcp.core.context.models import (
    ROLE_ENUM,
    ROLE_FOREIGN,
    ROLE_PII,
    ROLE_PRIMARY,
    ROLE_TENANT,
    ROLE_TIMESTAMP,
    FieldStat,
    SemanticsInput,
)
from guardmcp.core.context.semantics import FieldSemanticsAnalyzer
from guardmcp.core.pipeline import GuardPipeline
from guardmcp.core.policy.engine import PolicyEngine
from guardmcp.core.policy.models import CollectionPolicy, Policy
from guardmcp.core.risk.engine import RiskEngine

# ---------------------------------------------------------------------------
# 1. Data-agnostic structural detection (no English name tokens)
# ---------------------------------------------------------------------------


def test_structural_detection_no_english_tokens():
    """Roles detected with product-neutral names — proves no name vocab is required.

    - ``_id``  → primary_identifier  (sentinel name, structural)
    - ``grp``  → tenant_key          (high fan-in FK edge, purely structural)
    - ``xts``  → timestamp           (date type, purely structural)
    - ``cd``   → enum_status         (low-cardinality string, purely structural)
    """
    inp = SemanticsInput(
        resource="t",
        fields={"_id": "objectId", "grp": "objectId", "xts": "date", "cd": "string"},
        edges=[{"from_field": "grp", "to_resource": "g", "confidence": 0.75}],
        fan_in={"grp": 4},
        field_stats={
            "cd": FieldStat(count=100, distinct_count=3, sample_values=["a", "b", "c"])
        },
    )
    r = FieldSemanticsAnalyzer().analyze(inp).fields

    assert r["_id"].role == ROLE_PRIMARY, f"_id expected primary, got {r['_id'].role}"
    assert r["grp"].role == ROLE_TENANT, (
        f"grp expected tenant_key (structural fan-in), got {r['grp'].role}"
    )
    assert r["xts"].role == ROLE_TIMESTAMP, (
        f"xts expected timestamp (date type), got {r['xts'].role}"
    )
    assert r["cd"].role == ROLE_ENUM, (
        f"cd expected enum_status (low-cardinality), got {r['cd'].role}"
    )
    # enum must carry the actual values
    assert set(r["cd"].values) == {"a", "b", "c"}
    # tenant_key must point at the target resource
    assert r["grp"].references == "g"


# ---------------------------------------------------------------------------
# 2. Masked field never valued (analyzer-level proof)
# ---------------------------------------------------------------------------


def test_masked_field_never_valued_analyzer():
    """Masked field with populated stats stays pii, values=None — analyzer level."""
    inp = SemanticsInput(
        resource="user",
        fields={"password": "masked", "st": "string"},
        masked_fields=["password"],
        field_stats={
            "st": FieldStat(count=10, distinct_count=1, sample_values=["A"]),
            # Even though stats exist for password, values must NOT leak.
            "password": FieldStat(count=10, distinct_count=2, sample_values=["x", "y"]),
        },
    )
    r = FieldSemanticsAnalyzer().analyze(inp).fields

    assert r["password"].role == ROLE_PII, (
        f"masked field must be pii, got {r['password'].role}"
    )
    assert r["password"].values is None, (
        "masked field must NOT carry sample_values"
    )
    assert r["password"].pii is True


# ---------------------------------------------------------------------------
# Shared pipeline fixtures for end-to-end tests
# ---------------------------------------------------------------------------


class _FakeExecutor:
    """Stub executor: returns a small schema for 'items' and 'secrets'."""

    async def list_collections(self, database=None):
        return ["items", "users", "secrets"]

    async def collection_schema(self, collection, mask_fields, sample_size=None, database=None):
        schemas = {
            "items": {
                "_id": "objectId",
                "status": "string",
                "ssn": "masked",       # masked sensitive field
                "user_id": "objectId", # FK → users
            },
            "users": {
                "_id": "objectId",
            },
            "secrets": {
                "_id": "objectId",
                "token": "string",
            },
        }
        return schemas.get(collection, {})

    async def collection_indexes(self, collection, database=None):
        return []


class _FakePlugin:
    """Stub plugin: field_stats + relationships for 'items'."""

    async def field_stats(self, resource: str, mask_fields=None, database=None) -> dict:
        if resource == "items":
            return {
                "status": {
                    "count": 200,
                    "null_count": 0,
                    "distinct_count": 2,
                    "sample_values": ["active", "inactive"],
                },
                # Stats provided for masked field — must NOT surface values.
                "ssn": {
                    "count": 200,
                    "null_count": 0,
                    "distinct_count": 100,
                    "sample_values": ["123-45-6789"],
                },
            }
        return {}

    async def relationships(self, resources: list[str]) -> list[dict]:
        return [
            {
                "from_resource": "items",
                "from_field": "user_id",
                "to_resource": "users",
                "to_field": "_id",
                "kind": "naming",
                "confidence": 0.8,
                "evidence": "field name 'user_id' references 'users._id'",
            }
        ]


class _Audit:
    def __init__(self):
        self.actions: list[str] = []

    def build(self, **k):
        self.actions.append(k.get("action", ""))
        return k

    async def log(self, r):
        return None


def _pipeline(deny: list[str] | None = None):
    """Build a GuardPipeline with the fake executor/plugin and optional deny list."""
    ex = _FakeExecutor()
    plugin = _FakePlugin()

    class _Entry:
        executor = ex
        plugin_ = plugin

    entry = _Entry()
    entry.plugin = plugin  # attribute name expected by pipeline

    class _Registry:
        def get_active(self):
            return entry

        def get(self, n):
            return entry

    policy = Policy(
        agent="claude",
        collections=CollectionPolicy(allow=["*"], deny=deny or []),
        mask_fields=["ssn"],
    )

    class _Loader:
        def get(self, agent):
            return policy

    audit = _Audit()
    return (
        GuardPipeline(
            policy_loader=_Loader(),
            policy_engine=PolicyEngine(),
            risk_engine=RiskEngine(),
            audit_logger=audit,
            approval_store=None,
            executor=ex,
            registry=_Registry(),
        ),
        audit,
    )


# ---------------------------------------------------------------------------
# 3. End-to-end via describe_collection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_describe_collection_end_to_end_semantics():
    """describe_collection returns semantics with correct roles + values + masked_fields."""
    p, _ = _pipeline()
    out = await p.describe_collection("claude", "items")

    assert out is not None, "describe_collection must return a result for allowed collection"
    assert "fields" in out
    assert "semantics" in out
    assert "masked_fields" in out

    sem = out["semantics"]

    # _id → primary_identifier
    assert sem["_id"]["role"] == ROLE_PRIMARY, (
        f"_id must be primary_identifier, got {sem['_id']['role']}"
    )

    # status → enum_status with actual values (non-vacuous)
    assert sem["status"]["role"] == ROLE_ENUM, (
        f"status must be enum_status, got {sem['status']['role']}"
    )
    assert set(sem["status"]["values"]) == {"active", "inactive"}, (
        f"enum values mismatch: {sem['status']['values']}"
    )

    # user_id → foreign_identifier referencing users
    assert sem["user_id"]["role"] == ROLE_FOREIGN, (
        f"user_id must be foreign_identifier, got {sem['user_id']['role']}"
    )
    assert sem["user_id"]["references"] == "users", (
        f"user_id must reference 'users', got {sem['user_id']['references']}"
    )

    # ssn in masked_fields
    assert "ssn" in out["masked_fields"], "ssn must appear in masked_fields"

    # ssn semantics: pii role, values=None
    assert sem["ssn"]["role"] == ROLE_PII, (
        f"ssn must be pii, got {sem['ssn']['role']}"
    )
    assert sem["ssn"].get("values") is None, "masked ssn must NOT carry sample_values"


# ---------------------------------------------------------------------------
# 4. Governance: denied collection → None; masked field never valued
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_denied_collection_returns_none():
    """A denied collection must return None — no semantics, no schema."""
    p, _ = _pipeline(deny=["secrets"])
    out = await p.describe_collection("claude", "secrets")

    assert out is None, (
        f"denied collection must return None, got: {out}"
    )


@pytest.mark.asyncio
async def test_masked_field_never_valued_end_to_end():
    """Masked field (ssn) never carries a value in describe_collection output."""
    p, _ = _pipeline()
    out = await p.describe_collection("claude", "items")

    assert out is not None
    sem = out["semantics"]

    assert "ssn" in sem, "ssn must appear in semantics (as pii)"
    assert sem["ssn"].get("values") is None, (
        "masked field ssn must NOT carry values in end-to-end output"
    )
    assert sem["ssn"]["role"] == ROLE_PII


@pytest.mark.asyncio
async def test_allowed_collection_not_denied():
    """Sanity: an allowed collection is NOT blocked."""
    p, _ = _pipeline(deny=["secrets"])
    out = await p.describe_collection("claude", "items")

    assert out is not None, "items is allowed; must not return None"
    assert "semantics" in out
