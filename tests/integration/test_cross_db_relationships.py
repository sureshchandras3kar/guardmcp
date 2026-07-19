"""Integration tests — cross-database relationships v1.

Exercises the full end-to-end path through the ``guardmcp_relationships`` MCP
tool (registered via ``plan_query.register``) using the same fake-harness
pattern as the unit tests (Tasks 4 / 5).

Proves:
1. value_overlap edge: two databases sharing an id field with overlapping
   sampled values → a ``value_overlap`` cross_db_edge with the right endpoints
   and confidence > 0.5.
2. Governance – masked exclusion: a field whose describe_collection type is
   "masked" NEVER appears as an endpoint in any cross_db_edge.
3. Governance – db-allow scope: a database NOT in ``databases_allow`` is never
   scanned and never referenced in any edge.
4. Data-agnostic: product-neutral id field names (``grp_id``, ``xref_id``)
   matched purely structurally + by value overlap.
5. Back-compat: no ``databases_allow`` → ``cross_db_edges == []`` and the
   existing within-DB ``relationships`` key is still present in the response.
"""
from __future__ import annotations

import json

import pytest
from mcp.server.fastmcp import FastMCP

from guardmcp.core.policy.models import Policy
from guardmcp.server.tools._common import ToolContext
from guardmcp.server.tools.meta import plan_query  # noqa: E402

# ── Fake infrastructure ──────────────────────────────────────────────────────


class _Plugin:
    """Fake plugin that returns canned sample values per database."""

    name = "mongodb"
    _executor = None

    async def relationships(self, resources):
        return []

    async def sample_field_values(self, collection, field, database=None, cap=100):
        # Each db has a partially overlapping value set so overlap ratio = 1/2 ≥ OVERLAP_MIN(0.3)
        return {
            "crm": ["id-001", "id-002"],
            "billing": ["id-002", "id-003"],
            "analytics": ["x-1", "x-2"],
            "denied_db": ["secret"],
        }.get(database, [])


class _Entry:
    plugin = _Plugin()


class _Registry:
    def get_active(self):
        return _Entry()


class _Pipeline:
    """
    Fake pipeline.  Schema is configurable so individual tests can inject
    their own field/type layouts without building a new class each time.
    """

    def __init__(self, schema: dict[tuple[str, str], dict] | None = None):
        self._registry = _Registry()
        self._policies: _PolicyStore | None = None
        self._schema = schema or _default_schema()

    async def discover_collections(self, agent, database=None):
        cols = sorted(
            {col for (db, col) in self._schema if db == database}
        )
        return cols

    async def describe_collection(self, agent, collection, database=None):
        return self._schema.get((database, collection))


class _PolicyStore:
    def __init__(self, policy: Policy):
        self._p = policy

    def get(self, agent: str) -> Policy:
        return self._p


def _default_schema() -> dict[tuple[str, str], dict]:
    """Default schema: crm + billing share account_id; crm has masked ssn."""
    return {
        ("crm", "customer"): {
            "fields": {
                "account_id": "string",
                "name": "string",
                "ssn": "masked",  # must never appear in cross_db_edges
            }
        },
        ("billing", "invoice"): {
            "fields": {
                "account_id": "string",
                "amount": "number",
            }
        },
    }


def _register(policy: Policy, schema: dict | None = None) -> FastMCP:
    mcp = FastMCP("t")
    pipe = _Pipeline(schema)
    pipe._policies = _PolicyStore(policy)
    ctx = ToolContext(
        get_pipeline=lambda: pipe,
        get_agent=lambda: "claude",
        get_settings=lambda: None,
    )
    plan_query.register(mcp, ctx)
    return mcp


async def _call(mcp: FastMCP, name: str, **kw) -> dict:
    raw = await mcp._tool_manager.get_tool(name).fn(**kw)
    return json.loads(raw)


# ── Test 1: value_overlap edge with correct endpoints + confidence > 0.5 ─────


@pytest.mark.asyncio
async def test_value_overlap_edge_endpoints_and_confidence():
    """End-to-end: crm.customer.account_id ↔ billing.invoice.account_id
    with 1/2 overlap → kind='value_overlap', confidence > 0.5."""
    policy = Policy(agent="claude", databases_allow=["crm", "billing"])
    out = await _call(_register(policy), "guardmcp_relationships")

    assert out["ok"] is True
    edges = out["data"]["cross_db_edges"]
    assert edges, "expected at least one cross_db_edge"

    overlap_edges = [e for e in edges if e["kind"] == "value_overlap"]
    assert overlap_edges, "expected a value_overlap edge"

    # Find the account_id edge
    acct_edges = [
        e for e in overlap_edges
        if e["from"]["field"] == "account_id" or e["to"]["field"] == "account_id"
    ]
    assert acct_edges, "expected account_id to be an endpoint"

    e = acct_edges[0]
    # Both endpoints must name the field
    assert e["from"]["field"] == "account_id"
    assert e["to"]["field"] == "account_id"
    # Endpoints span crm and billing
    assert {e["from"]["database"], e["to"]["database"]} == {"crm", "billing"}
    # Confidence > 0.5 (value_overlap formula: 0.5 + 0.4*ratio, ratio=0.5 → 0.7)
    assert e["confidence"] > 0.5, f"confidence {e['confidence']} not > 0.5"


# ── Test 2: masked field never appears as an endpoint ─────────────────────────


@pytest.mark.asyncio
async def test_masked_field_never_endpoint():
    """ssn is typed 'masked' → must not appear in any cross_db_edge endpoint."""
    # Give billing a matching ssn field (not masked) to make it a *candidate*
    # if masking-exclusion were broken.
    schema = {
        ("crm", "customer"): {
            "fields": {
                "account_id": "string",
                "ssn": "masked",   # masked in crm
            }
        },
        ("billing", "invoice"): {
            "fields": {
                "account_id": "string",
                "ssn": "string",   # NOT masked in billing — tempting candidate
            }
        },
    }

    class _PluginWithSsn(_Plugin):
        async def sample_field_values(self, collection, field, database=None, cap=100):
            # Give ssn overlapping values so it would pass OVERLAP_MIN if not excluded
            ssn_vals = {
                "crm": ["999-00-0001", "999-00-0002"],
                "billing": ["999-00-0001", "999-00-0003"],
            }
            return ssn_vals.get(database, [])

    mcp = FastMCP("t")
    pipe = _Pipeline(schema)
    policy = Policy(agent="claude", databases_allow=["crm", "billing"])
    pipe._policies = _PolicyStore(policy)

    # Patch the registry to use the ssn-aware plugin
    class _EntryWithSsn:
        plugin = _PluginWithSsn()

    class _RegistryWithSsn:
        def get_active(self):
            return _EntryWithSsn()

    pipe._registry = _RegistryWithSsn()
    ctx = ToolContext(
        get_pipeline=lambda: pipe,
        get_agent=lambda: "claude",
        get_settings=lambda: None,
    )
    plan_query.register(mcp, ctx)
    out = await _call(mcp, "guardmcp_relationships")

    assert out["ok"] is True
    edges = out["data"]["cross_db_edges"]
    for e in edges:
        assert e["from"]["field"] != "ssn", "masked field ssn appeared as 'from' endpoint"
        assert e["to"]["field"] != "ssn", "masked field ssn appeared as 'to' endpoint"


# ── Test 3: denied database not scanned / not referenced ─────────────────────


@pytest.mark.asyncio
async def test_denied_database_absent_from_all_edges():
    """denied_db is NOT in databases_allow → never scanned, never in any edge."""
    schema = {
        ("crm", "customer"): {"fields": {"account_id": "string"}},
        ("billing", "invoice"): {"fields": {"account_id": "string"}},
        ("denied_db", "secret_col"): {"fields": {"account_id": "string"}},
    }
    # Only crm + billing are allowed; denied_db is deliberately omitted
    policy = Policy(agent="claude", databases_allow=["crm", "billing"])
    out = await _call(_register(policy, schema), "guardmcp_relationships")

    assert out["ok"] is True
    edges = out["data"]["cross_db_edges"]
    for e in edges:
        assert e["from"]["database"] != "denied_db", "denied_db appeared as 'from' database"
        assert e["to"]["database"] != "denied_db", "denied_db appeared as 'to' database"


# ── Test 4: data-agnostic – product-neutral id field names ───────────────────


@pytest.mark.asyncio
async def test_data_agnostic_neutral_id_field_names():
    """grp_id and xref_id end with '_id' → matched structurally, no hard-coded names."""
    schema = {
        ("platform", "group"): {"fields": {"grp_id": "string", "name": "string"}},
        ("reporting", "summary"): {"fields": {"grp_id": "string", "metric": "number"}},
        ("platform", "item"): {"fields": {"xref_id": "string"}},
        ("reporting", "detail"): {"fields": {"xref_id": "string"}},
    }

    class _NeutralPlugin(_Plugin):
        async def sample_field_values(self, collection, field, database=None, cap=100):
            # grp_id: 2 overlapping values across platform/reporting
            if field == "grp_id":
                grp = {"platform": ["g-1", "g-2"], "reporting": ["g-2", "g-3"]}
                return grp.get(database, [])
            # xref_id: 2 overlapping values
            if field == "xref_id":
                xref = {"platform": ["x-10", "x-20"], "reporting": ["x-10", "x-30"]}
                return xref.get(database, [])
            return []

    mcp = FastMCP("t")
    pipe = _Pipeline(schema)
    policy = Policy(agent="claude", databases_allow=["platform", "reporting"])
    pipe._policies = _PolicyStore(policy)

    class _EntryNeutral:
        plugin = _NeutralPlugin()

    class _RegistryNeutral:
        def get_active(self):
            return _EntryNeutral()

    pipe._registry = _RegistryNeutral()
    ctx = ToolContext(
        get_pipeline=lambda: pipe,
        get_agent=lambda: "claude",
        get_settings=lambda: None,
    )
    plan_query.register(mcp, ctx)
    out = await _call(mcp, "guardmcp_relationships")

    assert out["ok"] is True
    edges = out["data"]["cross_db_edges"]

    grp_edges = [
        e for e in edges
        if e["from"]["field"] == "grp_id" or e["to"]["field"] == "grp_id"
    ]
    assert grp_edges, "grp_id (neutral name) should produce a cross_db_edge"
    assert any(e["kind"] == "value_overlap" for e in grp_edges), \
        "grp_id edge should be value_overlap"

    xref_edges = [
        e for e in edges
        if e["from"]["field"] == "xref_id" or e["to"]["field"] == "xref_id"
    ]
    assert xref_edges, "xref_id (neutral name) should produce a cross_db_edge"


# ── Test 5: back-compat – no databases_allow → empty cross_db_edges ──────────


@pytest.mark.asyncio
async def test_no_databases_allow_gives_empty_cross_db_edges_and_preserves_relationships():
    """Policy without databases_allow → cross_db_edges == [] and relationships key present."""
    policy = Policy(agent="claude")  # no databases_allow at all
    out = await _call(_register(policy), "guardmcp_relationships")

    assert out["ok"] is True
    data = out["data"]

    # cross_db_edges must be empty (not missing, not None — exact empty list)
    assert "cross_db_edges" in data, "cross_db_edges key must always be present"
    assert data["cross_db_edges"] == [], \
        f"expected [], got {data['cross_db_edges']}"

    # Existing relationships key must still be present (back-compat)
    assert "relationships" in data, "relationships key must still be present"
    rel = data["relationships"]
    # Must have the standard RelationshipGraph shape
    assert "nodes" in rel
    assert "edges" in rel
    assert "generated_at" in rel
