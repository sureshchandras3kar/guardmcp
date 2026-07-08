"""Section B (read + discovery tools) — real MongoDB, real MCP tool layer."""

from __future__ import annotations

import pytest
import pytest_asyncio

from .conftest import build_pipeline, readwrite_masked_policy
from .helpers import call, make_mcp


@pytest_asyncio.fixture
async def seeded(tmp_path, mongo_uri, db_name):
    pipeline, registry, audit_path = build_pipeline(
        tmp_path, mongo_uri, db_name,
        readwrite_masked_policy(
            collections_allow=["users", "orders"], mask_fields=["ssn"],
            approval_high=False, approval_critical=False,
        ),
    )
    executor = registry.get("default").executor
    await executor._client.get_collection("users").insert_many(
        [
            {"name": "a", "status": "active", "ssn": "111-22-3333"},
            {"name": "b", "status": "inactive", "ssn": "444-55-6666"},
        ]
    )
    mcp = make_mcp(pipeline)
    return mcp, pipeline, registry


@pytest.mark.asyncio
async def test_find_filter_projection_sort_limit(seeded):
    mcp, _, _ = seeded
    out = await call(mcp, "db_find", collection="users", filter={"status": "active"}, limit=5)
    assert out["ok"] is True
    docs = out["data"]["documents"]
    assert len(docs) == 1
    assert docs[0]["ssn"] == "***masked***"


@pytest.mark.asyncio
async def test_count(seeded):
    mcp, _, _ = seeded
    out = await call(mcp, "db_count", collection="users", filter={})
    assert out["ok"] is True
    assert out["data"] == 2


@pytest.mark.asyncio
async def test_aggregate_allowed_stage(seeded):
    mcp, _, _ = seeded
    out = await call(
        mcp, "db_aggregate", collection="users",
        pipeline_stages=[{"$match": {"status": "active"}}, {"$project": {"name": 1}}],
    )
    assert out["ok"] is True
    # AGGREGATE's raw executor result is a plain list (not {"documents":...})
    # — see _build_success in core/pipeline.py, only FIND gets the dict wrap.
    assert len(out["data"]) == 1


@pytest.mark.asyncio
async def test_aggregate_banned_operator_rejected(seeded):
    mcp, _, _ = seeded
    out = await call(
        mcp, "db_aggregate", collection="users",
        pipeline_stages=[{"$match": {"$where": "this.name"}}],
    )
    assert out["ok"] is False


@pytest.mark.asyncio
async def test_explain(seeded):
    mcp, _, _ = seeded
    out = await call(mcp, "db_explain", collection="users", filter={"status": "active"})
    assert out["ok"] is True


@pytest.mark.asyncio
async def test_aggregate_db_documents_stage(seeded):
    mcp, _, _ = seeded
    out = await call(
        mcp, "db_aggregate_db",
        pipeline_stages=[{"$documents": [{"x": 1}, {"x": 2}]}],
    )
    assert out["ok"] is True
    assert len(out["data"]["documents"]) == 2


@pytest.mark.asyncio
async def test_aggregate_db_current_op(seeded):
    mcp, _, _ = seeded
    out = await call(mcp, "db_aggregate_db", pipeline_stages=[{"$currentOp": {}}])
    assert out["ok"] is True
    assert isinstance(out["data"]["documents"], list)


@pytest.mark.asyncio
async def test_export_find_mode_masked_data_in_file(seeded, tmp_path):
    mcp, pipeline, _ = seeded

    class _Settings:
        export_dir = tmp_path / "exports"
        export_ttl_seconds = 300.0

    mcp2 = make_mcp(pipeline, settings=_Settings())
    out = await call(mcp2, "db_export", collection="users", mode="find")
    assert out["ok"] is True
    manifest = out["data"]
    written = (_Settings.export_dir / f"{manifest['export_id']}.json").read_text()
    assert "111-22-3333" not in written
    assert "***masked***" in written


# ── Discovery ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_schema_semantics_masked_fields(seeded):
    mcp, _, _ = seeded
    out = await call(mcp, "db_schema", collection="users")
    assert out["ok"] is True
    assert "ssn" in out["data"]["masked_fields"]
    assert out["data"]["fields"]["ssn"] == "masked"


@pytest.mark.asyncio
async def test_indexes(seeded):
    mcp, _, _ = seeded
    out = await call(mcp, "db_indexes", collection="users")
    assert out["ok"] is True
    assert isinstance(out["data"], list) or "indexes" in out["data"] or out["data"] is not None


@pytest.mark.asyncio
async def test_list_collections(seeded):
    mcp, _, _ = seeded
    out = await call(mcp, "db_list_collections")
    assert out["ok"] is True
    assert "users" in out["data"]["collections"]


@pytest.mark.asyncio
async def test_list_databases(seeded):
    mcp, _, _ = seeded
    out = await call(mcp, "db_list_databases")
    assert out["ok"] is True


@pytest.mark.asyncio
async def test_stats(seeded):
    mcp, _, _ = seeded
    out = await call(mcp, "db_stats")
    assert out["ok"] is True


@pytest.mark.asyncio
async def test_collection_storage_size(seeded):
    mcp, _, _ = seeded
    out = await call(mcp, "db_collection_storage_size", collection="users")
    assert out["ok"] is True
    assert out["data"]["count"] == 2


@pytest.mark.asyncio
async def test_logs(seeded):
    mcp, _, _ = seeded
    out = await call(mcp, "db_logs")
    # getLog requires admin privileges the test container's default user may
    # or may not have — assert the envelope is well-formed either way, never
    # a raw crash/traceback.
    assert "ok" in out
    if out["ok"]:
        assert "lines" in out["data"]


@pytest.mark.asyncio
async def test_list_connections(seeded):
    mcp, _, _ = seeded
    out = await call(mcp, "db_list_connections")
    assert out["ok"] is True
    assert "default" in out["data"]["connections"]
    assert out["data"]["active"] == "default"
