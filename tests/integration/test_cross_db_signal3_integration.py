"""Integration tests: cross-DB signal-3 (identifier_alignment).

Proves:
1. End-to-end via guardmcp_relationships: identifier_alignment edge appears for a
   reference-based foreign_identifier -> primary_identifier link across two DBs.
2. Role-boost: a v1 shared-name/value-overlap edge whose endpoints are role-aligned
   is upgraded to identifier_alignment with higher confidence than the v1 base.
3. Governance — masked AND pii independently:
   (a) masked_fields exclusion: field in masked_fields never in any edge.
   (b) pii-role exclusion: field with role=pii (NOT in masked_fields) never in any edge.
4. Data-agnostic: product-neutral names (grp_ref/grps) align by role+reference only.
5. Back-compat: describe_collection with NO semantics -> only v1 edges (shared_name /
   value_overlap), NO identifier_alignment edges.
"""
from __future__ import annotations

import json

import pytest
from mcp.server.fastmcp import FastMCP

import guardmcp.server.tools._common as _common_mod
from guardmcp.core.planning.cross_db_resolver import CrossDatabaseResolver
from guardmcp.core.policy.models import Policy
from guardmcp.server.tools._common import ToolContext
from guardmcp.server.tools.meta import plan_query

# ---------------------------------------------------------------------------
# Shared harness helpers
# ---------------------------------------------------------------------------


class _DescribeMap:
    """Thin describe_collection dict-driven stub."""

    def __init__(self, collections_by_db: dict, describe_map: dict):
        self._coll = collections_by_db
        self._desc = describe_map

    async def discover_collections(self, agent, database=None):
        return self._coll.get(database, [])

    async def describe_collection(self, agent, collection, database=None):
        return self._desc.get((database, collection))


class _SamplePlugin:
    """Sample-values stub driven by a dict keyed (db, field)."""

    def __init__(self, values: dict):
        self._v = values

    async def sample_field_values(self, collection, field, database=None, cap=100):
        return self._v.get((database, field), [])


def _make_mcp(guard, plugin, policy: Policy):
    """Wire FastMCP + ToolContext mirroring the real server bootstrap."""
    mcp = FastMCP("t")

    class _Policies:
        def get(self, agent):
            return policy

    class _Pipeline:
        _policies = _Policies()

        async def discover_collections(self, agent, database=None):
            return await guard.discover_collections(agent, database=database)

        async def describe_collection(self, agent, collection, database=None):
            return await guard.describe_collection(agent, collection, database=database)

    pipeline = _Pipeline()

    ctx = ToolContext(
        get_pipeline=lambda: pipeline,
        get_agent=lambda: "claude",
        get_settings=lambda: None,
    )

    # Monkey-patch _active_plugin so the resolver gets our plugin
    import guardmcp.server.tools._common as _common_mod
    original_active = _common_mod._active_plugin

    def _patched_active(p):
        return plugin

    _common_mod._active_plugin = _patched_active
    plan_query.register(mcp, ctx)
    _common_mod._active_plugin = original_active

    # Store plugin on pipeline so tool can call it via lambda
    pipeline._plugin = plugin

    return mcp, pipeline, plugin


async def _call_relationships(mcp):
    return json.loads(await mcp._tool_manager.get_tool("guardmcp_relationships").fn())


# ---------------------------------------------------------------------------
# Proof 1: End-to-end — identifier_alignment edge via guardmcp_relationships
# ---------------------------------------------------------------------------


class _P1Guard(_DescribeMap):
    pass


class _P1Plugin(_SamplePlugin):
    pass


@pytest.mark.asyncio
async def test_e2e_identifier_alignment_via_tool():
    """P1: guardmcp_relationships emits identifier_alignment for a reference-based link."""
    guard = _DescribeMap(
        collections_by_db={"identity": ["user"], "billing": ["accounts"]},
        describe_map={
            ("identity", "user"): {
                "fields": {"_id": "objectId", "acct_ref": "string"},
                "semantics": {
                    "acct_ref": {"role": "foreign_identifier", "references": "accounts"},
                },
                "masked_fields": [],
            },
            ("billing", "accounts"): {
                "fields": {"_id": "objectId"},
                "semantics": {"_id": {"role": "primary_identifier"}},
                "masked_fields": [],
            },
        },
    )
    plugin = _SamplePlugin({
        ("identity", "acct_ref"): ["a", "b", "c"],
        ("billing", "_id"): ["b", "c", "d"],
    })

    # Exercise the resolver directly (mirrors the tool's internal path)
    resolver = CrossDatabaseResolver(guard, lambda: plugin)
    edges = await resolver.edges("claude", ["identity", "billing"])

    align = [e for e in edges if e.kind == "identifier_alignment"]
    assert align, "expected at least one identifier_alignment edge"

    e = align[0]
    # Assert real endpoint values
    assert e.from_.database == "identity"
    assert e.from_.collection == "user"
    assert e.from_.field == "acct_ref"
    assert e.to.database == "billing"
    assert e.to.collection == "accounts"
    assert e.to.field == "_id"
    assert e.kind == "identifier_alignment"
    assert e.confidence > 0.0


@pytest.mark.asyncio
async def test_e2e_identifier_alignment_via_tool_json():
    """P1b: same proof, but through the MCP JSON layer (guardmcp_relationships)."""
    guard = _DescribeMap(
        collections_by_db={"identity": ["user"], "billing": ["accounts"]},
        describe_map={
            ("identity", "user"): {
                "fields": {"_id": "objectId", "acct_ref": "string"},
                "semantics": {
                    "acct_ref": {"role": "foreign_identifier", "references": "accounts"},
                },
                "masked_fields": [],
            },
            ("billing", "accounts"): {
                "fields": {"_id": "objectId"},
                "semantics": {"_id": {"role": "primary_identifier"}},
                "masked_fields": [],
            },
        },
    )
    plugin = _SamplePlugin({
        ("identity", "acct_ref"): ["a", "b"],
        ("billing", "_id"): ["b", "c"],
    })

    policy = Policy(agent="claude", databases_allow=["identity", "billing"])

    mcp = FastMCP("t")

    class _Policies:
        def get(self, a):
            return policy

    class _Pipeline:
        _policies = _Policies()
        _plugin = plugin

        async def discover_collections(self, agent, database=None):
            return await guard.discover_collections(agent, database=database)

        async def describe_collection(self, agent, collection, database=None):
            return await guard.describe_collection(agent, collection, database=database)

    pipeline = _Pipeline()

    orig = _common_mod._active_plugin
    _common_mod._active_plugin = lambda p: plugin
    ctx = ToolContext(
        get_pipeline=lambda: pipeline,
        get_agent=lambda: "claude",
        get_settings=lambda: None,
    )
    plan_query.register(mcp, ctx)
    _common_mod._active_plugin = orig

    out = json.loads(await mcp._tool_manager.get_tool("guardmcp_relationships").fn())
    edges = out["data"]["cross_db_edges"]

    align = [e for e in edges if e["kind"] == "identifier_alignment"]
    assert align, "tool must emit at least one identifier_alignment edge"

    e = align[0]
    assert e["from"]["field"] == "acct_ref"
    assert e["from"]["database"] == "identity"
    assert e["to"]["database"] == "billing"
    assert e["to"]["field"] == "_id"


# ---------------------------------------------------------------------------
# Proof 2: Role-boost — shared-name edge upgraded to identifier_alignment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_role_boost_upgrades_shared_name_edge():
    """P2: a v1 shared_name edge with role-aligned endpoints gets boosted."""
    from guardmcp.core.planning.cross_db import boost_by_roles
    from guardmcp.core.planning.models import CrossDbEdge, CrossDbEndpoint

    # Craft a shared_name edge (low overlap -> kind=shared_name, conf=0.5)
    v1_edge = CrossDbEdge(
        **{"from": CrossDbEndpoint(database="identity", collection="user", field="account_id")},
        to=CrossDbEndpoint(database="billing", collection="accounts", field="account_id"),
        kind="shared_name",
        confidence=0.5,
        overlap_ratio=0.0,
        evidence="test v1 edge",
    )

    # Semantics: from=foreign_identifier, to=primary_identifier -> role-aligned pair
    semantics_by_loc = {
        ("identity", "user"): {
            "account_id": {"role": "foreign_identifier", "references": "accounts"},
        },
        ("billing", "accounts"): {
            "account_id": {"role": "primary_identifier"},
        },
    }

    boosted = boost_by_roles([v1_edge], semantics_by_loc)
    assert len(boosted) == 1
    b = boosted[0]
    # Kind upgraded
    assert b.kind == "identifier_alignment"
    # Confidence strictly higher than v1 base (0.5)
    assert b.confidence > 0.5, f"boosted confidence {b.confidence} not > 0.5"
    # Evidence preserved + role annotation appended
    assert "role-aligned" in b.evidence


# ---------------------------------------------------------------------------
# Proof 3a: Governance — masked field never appears in any edge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_masked_field_never_in_any_edge():
    """P3a: a field in masked_fields never appears as an endpoint in any edge."""
    guard = _DescribeMap(
        collections_by_db={"identity": ["user"], "billing": ["accounts"]},
        describe_map={
            ("identity", "user"): {
                "fields": {"_id": "objectId", "acct_ref": "string", "ssn": "masked"},
                "semantics": {
                    "acct_ref": {"role": "foreign_identifier", "references": "accounts"},
                    # ssn has a role but is masked
                    "ssn": {"role": "foreign_identifier", "references": "accounts"},
                },
                "masked_fields": ["ssn"],
            },
            ("billing", "accounts"): {
                "fields": {"_id": "objectId"},
                "semantics": {"_id": {"role": "primary_identifier"}},
                "masked_fields": [],
            },
        },
    )
    plugin = _SamplePlugin({
        ("identity", "acct_ref"): ["a", "b"],
        ("identity", "ssn"): ["x", "y"],
        ("billing", "_id"): ["b", "c"],
    })

    resolver = CrossDatabaseResolver(guard, lambda: plugin)
    edges = await resolver.edges("claude", ["identity", "billing"])

    for e in edges:
        assert e.from_.field != "ssn", f"masked field 'ssn' appeared in from endpoint: {e}"
        assert e.to.field != "ssn", f"masked field 'ssn' appeared in to endpoint: {e}"


# ---------------------------------------------------------------------------
# Proof 3b: Governance — pii-role field NOT in masked_fields also excluded
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pii_role_field_excluded_independently_of_masked_fields():
    """P3b: a field with role=pii that is NOT in masked_fields is also excluded."""
    guard = _DescribeMap(
        collections_by_db={"identity": ["user"], "billing": ["accounts"]},
        describe_map={
            ("identity", "user"): {
                # email is string (not 'masked' type), not in masked_fields, but role=pii
                "fields": {"_id": "objectId", "acct_ref": "string", "email": "string"},
                "semantics": {
                    "acct_ref": {"role": "foreign_identifier", "references": "accounts"},
                    "email": {"role": "pii"},  # pii-role, NOT masked_fields
                },
                "masked_fields": [],  # explicitly empty — no overlap with pii guard
            },
            ("billing", "accounts"): {
                "fields": {"_id": "objectId"},
                "semantics": {"_id": {"role": "primary_identifier"}},
                "masked_fields": [],
            },
        },
    )
    plugin = _SamplePlugin({
        ("identity", "acct_ref"): ["a", "b"],
        ("identity", "email"): ["u@x.com", "v@x.com"],
        ("billing", "_id"): ["b", "c"],
    })

    resolver = CrossDatabaseResolver(guard, lambda: plugin)
    edges = await resolver.edges("claude", ["identity", "billing"])

    # email must not appear regardless of masked_fields being empty
    for e in edges:
        assert e.from_.field != "email", (
            f"pii-role field 'email' appeared in from endpoint despite not being in "
            f"masked_fields: {e}"
        )
        assert e.to.field != "email", (
            f"pii-role field 'email' appeared in to endpoint: {e}"
        )

    # The valid acct_ref -> _id link must still work (test is non-vacuous)
    assert any(
        e.from_.field == "acct_ref" and e.to.field == "_id"
        for e in edges
    ), "acct_ref -> _id edge should still be present when email is excluded"


# ---------------------------------------------------------------------------
# Proof 4: Data-agnostic — product-neutral names align by role+reference only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_data_agnostic_neutral_names_align_by_role():
    """P4: grp_ref [references='grps'] -> grps._id purely by role, no English tokens."""
    guard = _DescribeMap(
        collections_by_db={"tenants": ["orgs"], "catalog": ["grps"]},
        describe_map={
            ("tenants", "orgs"): {
                "fields": {"_id": "objectId", "grp_ref": "string"},
                "semantics": {
                    "grp_ref": {"role": "foreign_identifier", "references": "grps"},
                },
                "masked_fields": [],
            },
            ("catalog", "grps"): {
                "fields": {"_id": "objectId"},
                "semantics": {"_id": {"role": "primary_identifier"}},
                "masked_fields": [],
            },
        },
    )
    plugin = _SamplePlugin({
        ("tenants", "grp_ref"): ["g1", "g2"],
        ("catalog", "_id"): ["g2", "g3"],
    })

    resolver = CrossDatabaseResolver(guard, lambda: plugin)
    edges = await resolver.edges("claude", ["tenants", "catalog"])

    align = [e for e in edges if e.kind == "identifier_alignment"]
    assert align, "expected identifier_alignment for grp_ref -> grps._id"

    e = align[0]
    assert e.from_.field == "grp_ref"
    assert e.from_.database == "tenants"
    assert e.to.collection == "grps"
    assert e.to.field == "_id"
    assert e.kind == "identifier_alignment"


# ---------------------------------------------------------------------------
# Proof 5: Back-compat — no semantics -> only v1 edges, no identifier_alignment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_back_compat_no_semantics_yields_only_v1_edges():
    """P5: describe_collection with NO semantics -> shared_name/value_overlap only."""
    guard = _DescribeMap(
        collections_by_db={"svc_a": ["items"], "svc_b": ["things"]},
        describe_map={
            # Both describe_collection returns lack 'semantics' entirely
            ("svc_a", "items"): {
                "fields": {"_id": "objectId", "thing_id": "string"},
                # no 'semantics' key
                "masked_fields": [],
            },
            ("svc_b", "things"): {
                "fields": {"_id": "objectId", "thing_id": "string"},
                # no 'semantics' key
                "masked_fields": [],
            },
        },
    )
    plugin = _SamplePlugin({
        ("svc_a", "thing_id"): ["x", "y"],
        ("svc_b", "thing_id"): ["y", "z"],
    })

    resolver = CrossDatabaseResolver(guard, lambda: plugin)
    edges = await resolver.edges("claude", ["svc_a", "svc_b"])

    # No identifier_alignment edges
    align = [e for e in edges if e.kind == "identifier_alignment"]
    assert not align, (
        f"back-compat broken: got identifier_alignment edges with no semantics: {align}"
    )

    # v1 edges must still be present (shared_name or value_overlap) — non-vacuous
    v1 = [e for e in edges if e.kind in ("shared_name", "value_overlap")]
    assert v1, "expected v1 edges (shared_name/value_overlap) when semantics absent"

    # Verify the kinds are only v1 kinds
    for e in edges:
        assert e.kind in ("shared_name", "value_overlap"), (
            f"unexpected edge kind '{e.kind}' in back-compat fixture"
        )
