import pytest

from guardmcp.core.planning.cross_db_resolver import CrossDatabaseResolver


class _Guard:
    async def discover_collections(self, agent, database=None):
        return {"identity": ["user"], "inventory": ["resource"], "secrets": ["s"]}.get(database, [])
    async def describe_collection(self, agent, collection, database=None):
        return {
            ("identity", "user"): {
                "fields": {"_id": "objectId", "account_id": "string", "email": "masked"},
            },
            ("inventory", "resource"): {"fields": {"_id": "objectId", "account_id": "string"}},
        }.get((database, collection))


class _Plugin:
    async def sample_field_values(self, collection, field, database=None, cap=100):
        return {"identity": ["a", "b"], "inventory": ["b", "c"]}[database]


@pytest.mark.asyncio
async def test_resolver_builds_cross_db_edge_on_shared_account_id():
    r = CrossDatabaseResolver(_Guard(), lambda: _Plugin())
    edges = await r.edges("claude", ["identity", "inventory"])
    acc = [e for e in edges if e.from_.field == "account_id"]
    assert acc, "expected an account_id cross-db edge"
    e = acc[0]
    assert {e.from_.database, e.to.database} == {"identity", "inventory"}
    assert e.kind == "value_overlap"  # a,b vs b,c overlap 1/2 >= 0.3


@pytest.mark.asyncio
async def test_masked_field_never_a_cross_db_candidate():
    r = CrossDatabaseResolver(_Guard(), lambda: _Plugin())
    edges = await r.edges("claude", ["identity", "inventory"])
    assert all(e.from_.field != "email" and e.to.field != "email" for e in edges)


@pytest.mark.asyncio
async def test_only_requested_databases_scanned():
    # 'secrets' not in the passed list -> never scanned -> no edge references it
    r = CrossDatabaseResolver(_Guard(), lambda: _Plugin())
    edges = await r.edges("claude", ["identity", "inventory"])
    assert all("secrets" not in (e.from_.database, e.to.database) for e in edges)
