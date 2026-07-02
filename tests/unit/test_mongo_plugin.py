import pytest

from guardmcp.core.interfaces.capability import (
    ACTION_TO_CAPABILITY,
    Capability,
    CapabilityRequest,
    CapabilityResult,
)
from guardmcp.core.interfaces.errors import GuardValidationError
from guardmcp.core.interfaces.plugin import DatabasePlugin
from guardmcp.core.models.domain import Action
from guardmcp.plugins.mongodb.executor import MongoExecutor
from guardmcp.plugins.mongodb.plugin import MongoPlugin


def test_is_database_plugin():
    p = MongoPlugin()
    assert isinstance(p, DatabasePlugin)
    assert p.name == "mongodb"
    assert p.api_version == "1.0"
    assert p.supported == frozenset(Capability)


def test_action_to_capability_covers_every_action():
    assert set(ACTION_TO_CAPABILITY) == set(Action)


def test_cross_resource_refs_extracts_lookup_and_unionwith():
    p = MongoPlugin()
    req = CapabilityRequest(
        capability=Capability.AGGREGATE,
        resource="customers",
        pipeline=[
            {"$lookup": {"from": "payroll", "localField": "id", "foreignField": "cid", "as": "p"}},
            {"$unionWith": "audit"},
            {"$unionWith": {"coll": "events", "pipeline": []}},
        ],
    )
    assert p.cross_resource_refs(req) == {"payroll", "audit", "events"}


def test_validate_request_rejects_banned_stage():
    p = MongoPlugin()
    req = CapabilityRequest(
        capability=Capability.AGGREGATE,
        resource="customers",
        pipeline=[{"$out": "exfil"}],
    )
    with pytest.raises(GuardValidationError):
        p.validate_request(req)


def test_validate_request_rejects_where_filter():
    p = MongoPlugin()
    req = CapabilityRequest(
        capability=Capability.READ,
        resource="customers",
        filter={"$where": "this.x == 1"},
    )
    with pytest.raises(GuardValidationError):
        p.validate_request(req)


def test_validate_request_passes_clean_find():
    p = MongoPlugin()
    req = CapabilityRequest(
        capability=Capability.READ,
        resource="customers",
        filter={"name": "alice"},
    )
    p.validate_request(req)  # should not raise


def test_alternative_requests_builds_aggregate_pipeline():
    p = MongoPlugin()
    read = CapabilityRequest(
        capability=Capability.READ, resource="customers",
        filter={"status": "ACTIVE"}, limit=10,
    )
    alts = p.alternative_requests(read)
    assert len(alts) == 1
    alt = alts[0]
    assert alt.strategy == "aggregation"
    assert alt.request.capability == Capability.AGGREGATE
    assert alt.request.resource == "customers"
    assert alt.request.pipeline == [{"$match": {"status": "ACTIVE"}}, {"$limit": 10}]


def test_alternative_requests_defaults_limit_when_absent():
    p = MongoPlugin()
    read = CapabilityRequest(
        capability=Capability.READ, resource="customers", filter={"status": "ACTIVE"},
    )
    alt = p.alternative_requests(read)[0]
    assert alt.request.pipeline[1] == {"$limit": 50}


def test_alternative_requests_empty_without_filter():
    p = MongoPlugin()
    read = CapabilityRequest(capability=Capability.READ, resource="customers")
    assert p.alternative_requests(read) == []


def test_alternative_requests_safe_default_is_empty():
    """A plugin that does not override the method (here Postgres) yields no
    alternatives — the base DatabasePlugin default is []."""
    from guardmcp.plugins.postgres.plugin import PostgresPlugin

    read = CapabilityRequest(
        capability=Capability.READ, resource="t", filter={"a": 1},
    )
    assert PostgresPlugin().alternative_requests(read) == []


@pytest.mark.asyncio
async def test_execute_read_roundtrip(executor: MongoExecutor):
    # seed a doc via the executor's underlying mongomock collection
    col = executor._client.get_collection("customers")
    await col.insert_one({"name": "alice", "age": 30})

    p = MongoPlugin(executor=executor)
    req = CapabilityRequest(
        capability=Capability.READ,
        resource="customers",
        filter={"name": "alice"},
        action=Action.FIND.value,
    )
    result = await p.execute(req)
    assert isinstance(result, CapabilityResult)
    assert len(result.rows) == 1
    assert result.rows[0]["name"] == "alice"


@pytest.mark.asyncio
async def test_list_resources_delegates(executor: MongoExecutor):
    col = executor._client.get_collection("orders")
    await col.insert_one({"x": 1})
    p = MongoPlugin(executor=executor)
    names = await p.list_resources()
    assert "orders" in names
