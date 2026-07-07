import pytest

from guardmcp.core.planning.cross_db import (
    _matches_resource,
    align_by_identifier_role,
    boost_by_roles,
    merge_edges,
)
from guardmcp.core.planning.models import CrossDbEdge, CrossDbEndpoint


def test_matches_resource_singular_plural():
    assert _matches_resource("account", "accounts")
    assert _matches_resource("Accounts", "account")
    assert _matches_resource("user", "user")
    assert not _matches_resource("user", "orders")


@pytest.mark.asyncio
async def test_reference_alignment_links_foreign_to_primary_diff_names():
    sem = {
        ("identity", "user"): {
            "acct_ref": {"role": "foreign_identifier", "references": "accounts"}
        },
        ("billing", "accounts"): {"_id": {"role": "primary_identifier", "references": None}},
    }
    values = {
        ("identity", "user", "acct_ref"): ["a", "b", "c"],
        ("billing", "accounts", "_id"): ["b", "c", "d"],
    }

    async def sampler(db, coll, field):
        return values.get((db, coll, field), [])

    edges = await align_by_identifier_role(sem, sampler)
    assert len(edges) == 1
    e = edges[0]
    assert e.kind == "identifier_alignment"
    assert (e.from_.database, e.from_.collection, e.from_.field) == (
        "identity",
        "user",
        "acct_ref",
    )
    assert (e.to.database, e.to.collection, e.to.field) == (
        "billing",
        "accounts",
        "_id",
    )
    assert e.confidence > 0.75  # value-overlap boosted (ratio 2/3)


@pytest.mark.asyncio
async def test_reference_alignment_needs_different_databases():
    sem = {
        ("identity", "user"): {
            "acct_id": {"role": "foreign_identifier", "references": "account"}
        },
        ("identity", "account"): {"_id": {"role": "primary_identifier", "references": None}},
    }

    async def sampler(db, coll, field):
        return []

    # same db -> not cross-db
    assert await align_by_identifier_role(sem, sampler) == []


@pytest.mark.asyncio
async def test_masked_or_non_identifier_never_aligns():
    sem = {
        ("a", "c1"): {"secret": {"role": "pii", "references": "accounts"}},
        ("b", "accounts"): {"_id": {"role": "primary_identifier", "references": None}},
    }

    async def sampler(db, coll, field):
        return []

    # pii role not foreign_identifier
    assert await align_by_identifier_role(sem, sampler) == []


def test_boost_by_roles_upgrades_aligned_v1_edge():
    edge = CrossDbEdge(
        **{"from": CrossDbEndpoint(database="a", collection="user", field="account_id")},
        to=CrossDbEndpoint(database="b", collection="accounts", field="account_id"),
        kind="value_overlap",
        confidence=0.7,
        overlap_ratio=0.5,
        evidence="v1",
    )
    sem = {
        ("a", "user"): {
            "account_id": {"role": "foreign_identifier", "references": "accounts"}
        },
        ("b", "accounts"): {
            "account_id": {"role": "primary_identifier", "references": None}
        },
    }
    out = boost_by_roles([edge], sem)
    assert (
        out[0].kind == "identifier_alignment"
        and out[0].confidence == pytest.approx(0.85)
    )


def test_boost_leaves_unaligned_edge_unchanged():
    edge = CrossDbEdge(
        **{"from": CrossDbEndpoint(database="a", collection="x", field="k_id")},
        to=CrossDbEndpoint(database="b", collection="y", field="k_id"),
        kind="shared_name",
        confidence=0.5,
        overlap_ratio=0.0,
        evidence="v1",
    )
    out = boost_by_roles([edge], {})  # no roles known
    assert out[0].kind == "shared_name" and out[0].confidence == 0.5


def test_merge_dedupes_keeping_higher_confidence():
    lo = CrossDbEdge(
        **{"from": CrossDbEndpoint(database="a", collection="u", field="acct_id")},
        to=CrossDbEndpoint(database="b", collection="accounts", field="_id"),
        kind="shared_name",
        confidence=0.5,
        evidence="lo",
    )
    hi = CrossDbEdge(
        **{"from": CrossDbEndpoint(database="b", collection="accounts", field="_id")},
        to=CrossDbEndpoint(database="a", collection="u", field="acct_id"),
        kind="identifier_alignment",
        confidence=0.9,
        evidence="hi",
    )
    merged = merge_edges([lo], [hi])
    # unordered pair dedup, higher wins
    assert len(merged) == 1 and merged[0].confidence == 0.9
