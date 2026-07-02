import pytest

from guardmcp.plugins.mongodb.relationships import infer_relationships


def test_naming_convention_edge():
    schemas = {"user": {"_id": "objectId", "name": "string"},
               "project": {"_id": "objectId", "user_id": "objectId"}}
    edges = infer_relationships(["user", "project"], schemas, {"user": [], "project": []})
    assert len(edges) == 1
    e = edges[0]
    assert (e["from_resource"], e["from_field"], e["to_resource"], e["to_field"]) == (
        "project", "user_id", "user", "_id")
    assert e["kind"] == "naming"
    assert e["confidence"] == 0.5


def test_indexed_fk_field_higher_confidence():
    schemas = {"user": {"_id": "objectId"},
               "project": {"_id": "objectId", "user_id": "objectId"}}
    indexes = {"user": [], "project": [{"name": "user_id_1", "key": [("user_id", 1)]}]}
    edges = infer_relationships(["user", "project"], schemas, indexes)
    assert edges[0]["kind"] == "index"
    assert edges[0]["confidence"] == 0.75


def test_no_edge_when_target_not_allowed():
    schemas = {"project": {"_id": "objectId", "user_id": "objectId"}}
    edges = infer_relationships(["project"], schemas, {"project": []})
    assert edges == []


class _FakeExecutor:
    async def collection_schema(self, collection, mask_fields, sample_size=None):
        return {"user": {"_id": "objectId"},
                "project": {"_id": "objectId", "user_id": "objectId"}}[collection]

    async def collection_indexes(self, collection):
        return []


@pytest.mark.asyncio
async def test_mongo_plugin_relationships_uses_executor():
    from guardmcp.plugins.mongodb.plugin import MongoPlugin
    plugin = MongoPlugin(executor=_FakeExecutor())
    edges = await plugin.relationships(["user", "project"])
    assert edges[0]["from_resource"] == "project"


@pytest.mark.asyncio
async def test_default_plugin_relationships_empty():
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

    assert await _Bare().relationships(["a", "b"]) == []
