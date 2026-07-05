import pytest

from guardmcp.core.planning.cross_db import cross_db_candidates, match_cross_db


def test_candidates_only_id_shaped_shared_across_databases():
    inv = {
        ("identity", "user"): {"_id", "account_id", "name"},
        ("inventory", "resource"): {"_id", "account_id", "status"},
        ("identity", "role"): {"_id", "account_id"},
    }
    cands = cross_db_candidates(inv)
    fields = {c[0] for c in cands}
    # account_id shared across identity+inventory (different dbs) -> candidate;
    # "name"/"status" not id-shaped -> excluded; _id is id-shaped and shared across dbs too.
    assert "account_id" in fields
    assert "name" not in fields and "status" not in fields
    # every candidate spans two DIFFERENT databases
    for _f, (dba, _ca), (dbb, _cb) in cands:
        assert dba != dbb


@pytest.mark.asyncio
async def test_value_overlap_upgrades_confidence():
    inv = {("identity", "user"): {"account_id"}, ("inventory", "resource"): {"account_id"}}
    values = {
        ("identity", "user", "account_id"): ["a", "b", "c"],
        ("inventory", "resource", "account_id"): ["b", "c", "d"],
    }

    async def sampler(db, coll, field):
        return values[(db, coll, field)]

    edges = await match_cross_db(inv, sampler)
    e = next(x for x in edges if x.from_.field == "account_id")
    assert (
        e.kind == "value_overlap"
        and e.confidence > 0.5
        and e.overlap_ratio == pytest.approx(2 / 3)
    )


@pytest.mark.asyncio
async def test_zero_overlap_stays_shared_name():
    inv = {("identity", "user"): {"account_id"}, ("inventory", "resource"): {"account_id"}}
    async def sampler(db, coll, field):
        return ["x", "y"] if db == "identity" else ["p", "q"]
    edges = await match_cross_db(inv, sampler)
    e = edges[0]
    assert e.kind == "shared_name" and e.confidence == 0.5 and e.overlap_ratio == 0.0


@pytest.mark.asyncio
async def test_deterministic():
    inv = {("a", "c1"): {"x_id"}, ("b", "c2"): {"x_id"}}
    async def sampler(db, coll, field): return ["1"]
    r1 = await match_cross_db(inv, sampler)
    r2 = await match_cross_db(inv, sampler)
    assert [e.model_dump(by_alias=True) for e in r1] == [e.model_dump(by_alias=True) for e in r2]
