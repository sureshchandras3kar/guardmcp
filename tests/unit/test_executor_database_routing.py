import pytest

from guardmcp.core.models.domain import Action
from guardmcp.plugins.mongodb.executor import MongoExecutor


class _Cursor:
    def __init__(self, docs): self._docs = docs
    def find(self, *a, **k): return self
    def sort(self, *a, **k): return self
    def skip(self, *a, **k): return self
    def limit(self, *a, **k): return self
    async def to_list(self, n): return self._docs


class _Coll:
    name = "user"
    def find(self, *a, **k): return _Cursor([{"_id": 1}])


class _FakeClient:
    def __init__(self): self.calls = []
    def get_collection(self, name, database=None):
        self.calls.append((name, database))
        return _Coll()
    def get_db(self, name=None):
        self.calls.append(("<db>", name))
        class _DB:
            async def command(self, *a, **k): return {"ok": 1}
            async def list_collection_names(self): return ["user"]
        return _DB()


async def _noop_type_map(collection, database=None):
    return {}


@pytest.mark.asyncio
async def test_execute_routes_collection_to_named_database():
    client = _FakeClient()
    ex = MongoExecutor(client)
    # Stub type_map_for so _marshal doesn't error on the fake collection
    ex._schema.type_map_for = _noop_type_map
    await ex.execute("user", Action.FIND, {"filter": {}}, database="other")
    assert ("user", "other") in client.calls


@pytest.mark.asyncio
async def test_execute_default_database_is_none():
    client = _FakeClient()
    ex = MongoExecutor(client)
    # Stub type_map_for so _marshal doesn't error on the fake collection
    ex._schema.type_map_for = _noop_type_map
    await ex.execute("user", Action.FIND, {"filter": {}})
    assert ("user", None) in client.calls
