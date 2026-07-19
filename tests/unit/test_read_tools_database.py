"""Tests: per-call `database` parameter on read/introspection tools (Task 4)."""

import json

import pytest
from mcp.server.fastmcp import FastMCP

from guardmcp.server.tools import read as read_tools
from guardmcp.server.tools._common import ToolContext


class _Pipeline:
    def __init__(self):
        self.run_calls = []

    _registry = None

    async def run(self, agent, collection, action, params, database=None):
        self.run_calls.append(
            (collection, action.value if hasattr(action, "value") else action, database)
        )
        return {"status": "success", "data": {"count": 0}}

    async def discover_collections(self, agent, database=None):
        self.run_calls.append(("<list>", "list", database))
        return []

    async def describe_collection(self, agent, collection, database=None):
        self.run_calls.append((collection, "describe", database))
        return {"collection": collection, "fields": {}}


def _register():
    mcp = FastMCP("t")
    pipe = _Pipeline()
    box = {"db": None}
    ctx = ToolContext(
        get_pipeline=lambda: pipe,
        get_agent=lambda: "claude",
        get_settings=lambda: None,
        get_active_database=lambda: box["db"],
        set_active_database=lambda v: box.__setitem__("db", v),
    )
    read_tools.register(mcp, ctx)
    return mcp, pipe, box


async def _call(mcp, name, **kw):
    return json.loads(await mcp._tool_manager.get_tool(name).fn(**kw))


@pytest.mark.asyncio
async def test_count_threads_per_call_database():
    """Per-call database is passed through to pipeline.run for count."""
    mcp, pipe, _ = _register()
    await _call(mcp, "mongodb_count", collection="user", filter={}, database="db1")
    assert any(c[0] == "user" and c[2] == "db1" for c in pipe.run_calls)


@pytest.mark.asyncio
async def test_count_uses_active_database_when_omitted():
    """Omitting database falls back to session active db."""
    mcp, pipe, box = _register()
    box["db"] = "sessiondb"
    await _call(mcp, "mongodb_count", collection="user", filter={})
    assert any(c[0] == "user" and c[2] == "sessiondb" for c in pipe.run_calls)


@pytest.mark.asyncio
async def test_count_uses_none_when_no_active_db():
    """Omitting database with no active session db passes None."""
    mcp, pipe, _ = _register()
    await _call(mcp, "mongodb_count", collection="user", filter={})
    assert any(c[0] == "user" and c[2] is None for c in pipe.run_calls)


@pytest.mark.asyncio
async def test_list_collections_threads_per_call_database():
    """Per-call database is passed through to discover_collections."""
    mcp, pipe, _ = _register()
    await _call(mcp, "mongodb_list_collections", database="mydb")
    assert any(c[0] == "<list>" and c[2] == "mydb" for c in pipe.run_calls)


@pytest.mark.asyncio
async def test_list_collections_uses_active_database_when_omitted():
    """Omitting database on list_collections uses the active session db."""
    mcp, pipe, box = _register()
    box["db"] = "active_db"
    await _call(mcp, "mongodb_list_collections")
    assert any(c[0] == "<list>" and c[2] == "active_db" for c in pipe.run_calls)


@pytest.mark.asyncio
async def test_find_threads_per_call_database():
    """Per-call database is passed through to pipeline.run for find."""
    mcp, pipe, _ = _register()
    await _call(mcp, "mongodb_find", collection="orders", filter={}, database="analytics")
    assert any(c[0] == "orders" and c[2] == "analytics" for c in pipe.run_calls)


@pytest.mark.asyncio
async def test_aggregate_threads_per_call_database():
    """Per-call database is passed through to pipeline.run for aggregate."""
    mcp, pipe, _ = _register()
    await _call(
        mcp,
        "mongodb_aggregate",
        collection="events",
        pipeline_stages=[{"$match": {}}],
        database="events_db",
    )
    assert any(c[0] == "events" and c[2] == "events_db" for c in pipe.run_calls)


@pytest.mark.asyncio
async def test_indexes_threads_per_call_database():
    """Per-call database is passed through to pipeline.run for indexes."""
    mcp, pipe, _ = _register()
    await _call(mcp, "mongodb_collection_indexes", collection="users", database="proddb")
    assert any(c[0] == "users" and c[2] == "proddb" for c in pipe.run_calls)
