import pytest


class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    def limit(self, n):
        self._docs = self._docs[:n]
        return self

    async def to_list(self, n):
        return self._docs


class _Coll:
    def find(self, filt, proj):
        return _Cursor(
            [{"account_id": "a"}, {"account_id": "b"}, {"account_id": "a"}]
        )


class _Client:
    def get_collection(self, name, database=None):
        return _Coll()


@pytest.mark.asyncio
async def test_executor_sample_field_values_distinct():
    from guardmcp.plugins.mongodb.executor import MongoExecutor

    ex = MongoExecutor(_Client())
    vals = await ex.sample_field_values("user", "account_id", database="identity", cap=100)
    assert set(vals) == {"a", "b"}


@pytest.mark.asyncio
async def test_plugin_sample_field_values_delegates_and_guards():
    from guardmcp.plugins.mongodb.plugin import MongoPlugin

    class _Ex:
        async def sample_field_values(self, c, f, database=None, cap=100):
            return ["x"]

    assert await MongoPlugin(executor=_Ex()).sample_field_values("u", "account_id") == ["x"]

    class _Boom:
        async def sample_field_values(self, *a, **k):
            raise RuntimeError("x")

    assert await MongoPlugin(executor=_Boom()).sample_field_values("u", "account_id") == []


@pytest.mark.asyncio
async def test_default_plugin_sample_field_values_empty():
    from guardmcp.core.interfaces.plugin import DatabasePlugin

    class _Bare(DatabasePlugin):
        name = "bare"
        supported = frozenset()

        async def connect(self, dsn, options): ...

        async def health(self):
            return True

        async def close(self): ...

        async def execute(self, req): ...

        async def schema(self, resource, sample_size=None):
            return {}

        async def list_resources(self):
            return []

        def validate_request(self, req): ...

    assert await _Bare().sample_field_values("u", "f") == []
