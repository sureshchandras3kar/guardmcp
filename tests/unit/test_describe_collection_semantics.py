"""Tests: describe_collection attaches per-field semantics + masked_fields.

Adapted for the multi-DB aware describe_collection (database-aware, masked-as-"masked").
Masked fields appear in schema as {field: "masked"} — they are NOT stripped.
"""
import pytest

from guardmcp.core.pipeline import GuardPipeline
from guardmcp.core.policy.engine import PolicyEngine
from guardmcp.core.policy.models import CollectionPolicy, Policy
from guardmcp.core.risk.engine import RiskEngine

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

class _Executor:
    """Minimal executor stub: schema returns masked fields with type "masked"."""

    def __init__(self):
        self.calls: list = []

    async def list_collections(self, database=None):
        self.calls.append(("list", database))
        return ["user", "orders"]

    async def collection_schema(self, collection, mask_fields, sample_size=None, database=None):
        self.calls.append(("schema", collection, database))
        schemas = {
            "user": {
                "_id": "objectId",
                "email": "masked",   # masked field — type is "masked"
                "status": "string",
            },
            "orders": {
                "_id": "objectId",
                "user_id": "objectId",
            },
        }
        return schemas.get(collection, {})

    async def collection_indexes(self, collection, database=None):
        self.calls.append(("indexes", collection, database))
        return []


class _Plugin:
    """Minimal plugin stub with field_stats and relationships."""

    async def field_stats(
        self, resource: str, mask_fields=None, database=None
    ) -> dict:
        if resource == "user":
            return {
                "status": {
                    "count": 100,
                    "null_count": 0,
                    "distinct_count": 2,
                    "sample_values": ["ACTIVE", "INACTIVE"],
                }
            }
        return {}

    async def relationships(self, resources: list[str]) -> list[dict]:
        return [
            {
                "from_resource": "orders",
                "from_field": "user_id",
                "to_resource": "user",
                "to_field": "_id",
                "kind": "naming",
                "confidence": 0.5,
                "evidence": "field name 'user_id' references 'user._id'",
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


def _make_pipeline(mask_fields=None):
    """Build a minimal GuardPipeline with stub executor/plugin/registry.

    Returns (pipeline, audit) so tests can inspect recorded audit actions.
    """
    ex = _Executor()
    plugin = _Plugin()

    entry_executor = ex
    entry_plugin = plugin

    class _Entry:
        executor = entry_executor
        plugin = entry_plugin

    entry = _Entry()

    class _Registry:
        def get_active(self): return entry
        def get(self, n): return entry

    # Policy: allow all collections, mask email globally
    mf = mask_fields if mask_fields is not None else ["email"]
    policy = Policy(
        agent="claude",
        collections=CollectionPolicy(allow=["*"], deny=[]),
        mask_fields=mf,
    )

    class _Loader:
        def get(self, agent): return policy

    audit = _Audit()
    pipeline = GuardPipeline(
        policy_loader=_Loader(),
        policy_engine=PolicyEngine(),
        risk_engine=RiskEngine(),
        audit_logger=audit,
        approval_store=None,
        executor=ex,
        registry=_Registry(),
    )
    return pipeline, audit


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_describe_includes_semantics_and_masked():
    """Core assertions: primary _id, enum status, masked email as pii."""
    p, _ = _make_pipeline()
    out = await p.describe_collection("claude", "user")

    # fields still present (additive)
    assert out["fields"]["_id"] == "objectId"
    # email is masked — schema value is "masked", NOT stripped
    assert out["fields"]["email"] == "masked"

    # semantics attached
    assert "semantics" in out
    assert out["semantics"]["_id"]["role"] == "primary_identifier"

    # status: low-cardinality string → enum_status with sample values
    assert out["semantics"]["status"]["role"] == "enum_status"
    assert set(out["semantics"]["status"]["values"]) == {"ACTIVE", "INACTIVE"}

    # email: masked field → pii role
    assert out["semantics"]["email"]["role"] == "pii"

    # masked_fields list present and contains email
    assert "masked_fields" in out
    assert "email" in out["masked_fields"]


@pytest.mark.asyncio
async def test_describe_foreign_reference():
    """orders.user_id has a FK edge → foreign_identifier referencing user."""
    p, _ = _make_pipeline()
    out = await p.describe_collection("claude", "orders")

    assert "semantics" in out
    assert out["semantics"]["user_id"]["role"] == "foreign_identifier"
    assert out["semantics"]["user_id"]["references"] == "user"

    # No masked fields in orders
    assert out["masked_fields"] == []


@pytest.mark.asyncio
async def test_masked_field_never_carries_value():
    """Masked fields must NOT carry sample_values in semantics."""
    p, _ = _make_pipeline()
    out = await p.describe_collection("claude", "user")

    email_sem = out["semantics"]["email"]
    assert email_sem.get("values") is None, "masked field must not carry sample_values"
    assert email_sem["role"] == "pii"
    assert email_sem.get("pii") is True


@pytest.mark.asyncio
async def test_backcompat_no_database_returns_semantics():
    """describe_collection with no database arg still returns semantics (back-compat)."""
    p, _ = _make_pipeline()
    out = await p.describe_collection("claude", "user")

    assert out is not None
    assert "fields" in out
    assert "semantics" in out
    assert "masked_fields" in out


@pytest.mark.asyncio
async def test_semantics_best_effort_no_plugin():
    """When plugin is absent, semantics still returns (degraded: None or partial)."""
    ex = _Executor()

    class _RegistryNoPlugin:
        def get_active(self):
            class _Entry:
                executor = ex
                plugin = None  # no plugin attribute that is a valid plugin
            return _Entry()

    policy = Policy(
        agent="claude",
        collections=CollectionPolicy(allow=["*"], deny=[]),
        mask_fields=["email"],
    )

    class _Loader:
        def get(self, agent): return policy

    p = GuardPipeline(
        policy_loader=_Loader(),
        policy_engine=PolicyEngine(),
        risk_engine=RiskEngine(),
        audit_logger=_Audit(),
        approval_store=None,
        executor=ex,
        registry=_RegistryNoPlugin(),
    )
    # Must not raise; should return at minimum fields + masked_fields
    out = await p.describe_collection("claude", "user")
    assert out is not None
    assert "fields" in out
    assert "masked_fields" in out


@pytest.mark.asyncio
async def test_empty_collection_returns_note():
    """Empty collection returns the empty-schema note (unchanged behavior)."""
    ex = _Executor()

    async def _empty_schema(collection, mask_fields, sample_size=None, database=None):
        return {}

    ex.collection_schema = _empty_schema

    policy = Policy(
        agent="claude",
        collections=CollectionPolicy(allow=["*"], deny=[]),
    )

    class _Loader:
        def get(self, agent): return policy

    p = GuardPipeline(
        policy_loader=_Loader(),
        policy_engine=PolicyEngine(),
        risk_engine=RiskEngine(),
        audit_logger=_Audit(),
        approval_store=None,
        executor=ex,
    )
    out = await p.describe_collection("claude", "user")
    assert out is not None
    assert out.get("note") == "collection is empty"
    assert out["fields"] == {}


@pytest.mark.asyncio
async def test_describe_collection_no_spurious_list_collections_audit():
    """describe_collection must NOT emit a list_collections audit event.

    The fan-in computation inside _field_semantics uses the executor directly
    (unaudited), so only a single 'collection_schema' event should appear in
    the audit trail for each describe_collection call.
    """
    p, audit = _make_pipeline()
    await p.describe_collection("claude", "user")

    assert "collection_schema" in audit.actions, (
        "expected a collection_schema audit event"
    )
    assert "list_collections" not in audit.actions, (
        f"spurious list_collections audit event emitted: {audit.actions}"
    )
