from datetime import UTC, datetime

import pytest

from guardmcp.plugins.mongodb.schema import build_field_stats


def test_build_field_stats_counts_and_distinct():
    docs = [{"a": "X"}, {"a": "Y"}, {"a": "X"}, {"a": None}]
    s = build_field_stats(docs, [])
    assert s["a"]["count"] == 4
    assert s["a"]["null_count"] == 1
    assert s["a"]["distinct_count"] == 2
    assert set(s["a"]["sample_values"]) == {"X", "Y"}


# ── Data-trust signal v1: freshness (min/max sampled datetime) ──────────────


def test_datetime_field_gets_min_max_value():
    t1 = datetime(2024, 1, 1, tzinfo=UTC)
    t2 = datetime(2025, 6, 1, tzinfo=UTC)
    t3 = datetime(2024, 12, 1, tzinfo=UTC)
    docs = [{"updated_at": t1}, {"updated_at": t2}, {"updated_at": t3}]
    s = build_field_stats(docs, [])
    assert s["updated_at"]["min_value"] == t1
    assert s["updated_at"]["max_value"] == t2


def test_non_datetime_field_has_no_min_max():
    docs = [{"a": "X"}, {"a": "Y"}]
    s = build_field_stats(docs, [])
    assert s["a"]["min_value"] is None
    assert s["a"]["max_value"] is None


def test_masked_datetime_field_has_no_min_max():
    t1 = datetime(2024, 1, 1, tzinfo=UTC)
    docs = [{"deleted_at": t1}]
    s = build_field_stats(docs, ["deleted_at"])
    assert s["deleted_at"]["min_value"] is None
    assert s["deleted_at"]["max_value"] is None


def test_build_field_stats_counts_absent_as_null():
    docs = [{"a": 1}, {"b": 2}]  # 'a' absent in second doc
    s = build_field_stats(docs, [])
    assert s["a"]["count"] == 2 and s["a"]["null_count"] == 1


def test_masked_field_has_no_values():
    docs = [{"password": "secret1"}, {"password": "secret2"}]
    s = build_field_stats(docs, ["password"])
    assert s["password"]["sample_values"] is None
    assert s["password"]["distinct_count"] is None


class _FakeExec:
    async def field_stats(self, collection, mask_fields, database=None):
        return {"a": {"count": 1, "null_count": 0, "distinct_count": 1, "sample_values": ["X"]}}


@pytest.mark.asyncio
async def test_plugin_field_stats_delegates():
    from guardmcp.plugins.mongodb.plugin import MongoPlugin
    plugin = MongoPlugin(executor=_FakeExec())
    out = await plugin.field_stats("user", ["password"])
    assert out["a"]["distinct_count"] == 1


@pytest.mark.asyncio
async def test_default_plugin_field_stats_empty():
    from guardmcp.core.interfaces.plugin import DatabasePlugin

    class _Bare(DatabasePlugin):
        name = "bare"
        supported = frozenset()
        async def connect(self, dsn, options): ...
        async def health(self): return True
        async def close(self): ...
        async def execute(self, req): ...
        async def schema(self, resource, sample_size=None): return {}
        async def list_resources(self): return []
        def validate_request(self, req): ...

    assert await _Bare().field_stats("user") == {}


class _FakeClient:
    """Fake MongoClient that records the database argument passed to get_collection."""

    def __init__(self):
        self.called_with_database = None
        self._col = _FakeCollection()

    def get_collection(self, name, database=None):
        self.called_with_database = database
        return self._col

    async def list_collection_names(self, database=None):
        return []


class _FakeCollection:
    """Fake Motor collection whose find().limit().to_list() returns a small sample."""

    def find(self, *args, **kwargs):
        return self

    def limit(self, n):
        return self

    async def to_list(self, n):
        return [{"x": 1}, {"x": 2}]


@pytest.mark.asyncio
async def test_executor_field_stats_routes_database():
    """executor.field_stats(collection, mask_fields, database=db) must pass
    database= through to the underlying client.get_collection call."""
    from guardmcp.plugins.mongodb.executor import MongoExecutor

    fake_client = _FakeClient()
    executor = MongoExecutor(fake_client, schema_cache_ttl=300)
    await executor.field_stats("user", [], database="db1")
    assert fake_client.called_with_database == "db1"


@pytest.mark.asyncio
async def test_schema_cache_field_stats_with_ttl_zero():
    """When schema_cache_ttl=0 (caching disabled), field_stats must sample
    directly and return real stats instead of silently returning empty dict."""
    from guardmcp.plugins.mongodb.schema_cache import MongoSchemaCache

    class _FakeCacheTTLClient:
        """Fake client that returns a collection with sample docs."""
        def get_collection(self, name, database=None):
            return _FakeCacheTTLCollection()

        async def list_collection_names(self, database=None):
            return []

    class _FakeCacheTTLCollection:
        """Fake collection that yields sample docs with distinct values."""
        def find(self, *args, **kwargs):
            return self

        def limit(self, n):
            return self

        async def to_list(self, n):
            return [{"a": "X"}, {"a": "Y"}, {"a": "X"}]

    fake_client = _FakeCacheTTLClient()
    cache = MongoSchemaCache(fake_client, schema_cache_ttl=0)
    stats = await cache.field_stats("test_col", [])

    # With ttl=0, cache is bypassed but stats should still be computed from sample
    assert "a" in stats
    assert stats["a"]["distinct_count"] == 2
    assert set(stats["a"]["sample_values"]) == {"X", "Y"}
    assert stats["a"]["count"] == 3
