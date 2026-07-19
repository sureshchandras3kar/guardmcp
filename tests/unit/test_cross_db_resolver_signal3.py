import pytest

from guardmcp.core.planning.cross_db_resolver import CrossDatabaseResolver


class _Guard:
    async def discover_collections(self, agent, database=None):
        return {"identity": ["user"], "billing": ["accounts"]}.get(database, [])
    async def describe_collection(self, agent, collection, database=None):
        return {
            ("identity", "user"): {
                "fields": {"_id": "objectId", "acct_ref": "string", "email": "masked"},
                "semantics": {
                    "acct_ref": {"role": "foreign_identifier", "references": "accounts"},
                    "email": {"role": "pii"},
                },
                "masked_fields": ["email"],
            },
            ("billing", "accounts"): {
                "fields": {"_id": "objectId"},
                "semantics": {"_id": {"role": "primary_identifier"}},
                "masked_fields": [],
            },
        }.get((database, collection))


class _Plugin:
    async def sample_field_values(self, collection, field, database=None, cap=100):
        return {("identity", "acct_ref"): ["a", "b"], ("billing", "_id"): ["b", "c"]}.get(
            (database, field), [])


@pytest.mark.asyncio
async def test_resolver_emits_identifier_alignment_edge():
    r = CrossDatabaseResolver(_Guard(), lambda: _Plugin())
    edges = await r.edges("claude", ["identity", "billing"])
    align = [e for e in edges if e.kind == "identifier_alignment"]
    assert align, "expected an identifier_alignment edge from acct_ref -> accounts._id"
    e = align[0]
    assert (e.from_.collection, e.from_.field) == ("user", "acct_ref")
    assert (e.to.collection, e.to.field) == ("accounts", "_id")


@pytest.mark.asyncio
async def test_masked_field_never_in_signal3_edges():
    r = CrossDatabaseResolver(_Guard(), lambda: _Plugin())
    edges = await r.edges("claude", ["identity", "billing"])
    assert all(e.from_.field != "email" and e.to.field != "email" for e in edges)
