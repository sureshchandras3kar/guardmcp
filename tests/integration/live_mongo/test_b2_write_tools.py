"""Section B (write tools) — real MongoDB. Each: allowed path executes for
real; denied path (policy/readonly) leaves data untouched; approval-required
path only executes after confirm.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from .conftest import build_pipeline, readwrite_masked_policy
from .helpers import ConfirmingContext, DecliningContext, call, make_mcp


@pytest_asyncio.fixture
async def rw(tmp_path, mongo_uri, db_name):
    """readwrite, no approval gates — for allowed/denied path checks."""
    pipeline, registry, _ = build_pipeline(
        tmp_path, mongo_uri, db_name,
        readwrite_masked_policy(
            collections_allow=["users", "orders", "staging"],
            mask_fields=[], approval_high=False, approval_critical=False,
        ),
    )
    executor = registry.get("default").executor
    mcp = make_mcp(pipeline)
    return mcp, executor, pipeline


@pytest_asyncio.fixture
async def rw_approval(tmp_path, mongo_uri, db_name):
    """readwrite WITH approval gates — for the confirm/decline paths."""
    pipeline, registry, _ = build_pipeline(
        tmp_path, mongo_uri, db_name,
        readwrite_masked_policy(collections_allow=["orders"], mask_fields=[]),
    )
    executor = registry.get("default").executor
    mcp = make_mcp(pipeline)
    return mcp, executor, pipeline


@pytest.mark.asyncio
async def test_insert_one_many(rw):
    mcp, executor, _ = rw
    out1 = await call(mcp, "db_insert_one", collection="users", document={"name": "a"})
    assert out1["ok"] is True
    out2 = await call(
        mcp, "db_insert_many", collection="users", documents=[{"name": "b"}, {"name": "c"}]
    )
    assert out2["ok"] is True
    docs = await executor._client.get_collection("users").find({}).to_list(10)
    assert len(docs) == 3


@pytest.mark.asyncio
async def test_update_one_many(rw):
    mcp, executor, _ = rw
    await executor._client.get_collection("orders").insert_many(
        [{"status": "open"}, {"status": "open"}]
    )
    out1 = await call(
        mcp, "db_update_one", collection="orders",
        filter={"status": "open"}, update={"$set": {"status": "shipped"}},
    )
    assert out1["ok"] is True
    out2 = await call(
        mcp, "db_update_many", collection="orders",
        filter={"status": "open"}, update={"$set": {"status": "cancelled"}},
    )
    assert out2["ok"] is True
    remaining_open = await executor._client.get_collection("orders").count_documents(
        {"status": "open"}
    )
    assert remaining_open == 0


@pytest.mark.asyncio
async def test_create_index_drop_index(rw):
    mcp, executor, _ = rw
    out1 = await call(mcp, "db_create_index", collection="users", keys={"name": 1})
    assert out1["ok"] is True
    idx = await executor._client.get_collection("users").index_information()
    assert "name_1" in idx

    out2 = await call(mcp, "db_drop_index", collection="users", index_name="name_1")
    assert out2["ok"] is True
    idx2 = await executor._client.get_collection("users").index_information()
    assert "name_1" not in idx2


@pytest.mark.asyncio
async def test_create_rename_drop_collection(rw):
    mcp, executor, _ = rw
    out1 = await call(mcp, "db_create_collection", collection="staging")
    assert out1["ok"] is True
    names = await executor._client.list_collection_names()
    assert "staging" in names

    out2 = await call(mcp, "db_rename_collection", collection="staging", new_name="staging2")
    assert out2["ok"] is True
    names2 = await executor._client.list_collection_names()
    assert "staging2" in names2 and "staging" not in names2

    # drop_collection tool needs "staging2" allowed — policy allows "staging"
    # only, so exercise drop on an already-allowed collection instead.
    await executor._client.get_collection("users").insert_one({"x": 1})
    out3 = await call(mcp, "db_drop_collection", collection="users")
    assert out3["ok"] is True
    names3 = await executor._client.list_collection_names()
    assert "users" not in names3


# ── Denied path: readonly leaves data untouched ─────────────────────────────


@pytest.mark.asyncio
async def test_write_denied_in_readonly_leaves_data_untouched(tmp_path, mongo_uri, db_name):
    from .conftest import readonly_allow_all_policy

    pipeline, registry, _ = build_pipeline(
        tmp_path, mongo_uri, db_name, readonly_allow_all_policy()
    )
    executor = registry.get("default").executor
    mcp = make_mcp(pipeline)

    out = await call(mcp, "db_insert_one", collection="users", document={"name": "x"})
    assert out["ok"] is False
    count = await executor._client.get_collection("users").count_documents({})
    assert count == 0


# ── Approval-required: confirm executes, decline never executes ────────────


@pytest.mark.asyncio
async def test_delete_many_confirmed_executes(rw_approval):
    mcp, executor, _ = rw_approval
    await executor._client.get_collection("orders").insert_many([{"_id": 1}, {"_id": 2}])

    tool = mcp._tool_manager.get_tool("db_delete_many")
    import json

    out = json.loads(await tool.fn(ConfirmingContext(), collection="orders", filter={}))
    assert out["ok"] is True
    remaining = await executor._client.get_collection("orders").count_documents({})
    assert remaining == 0


@pytest.mark.asyncio
async def test_delete_many_declined_never_executes(rw_approval):
    mcp, executor, _ = rw_approval
    await executor._client.get_collection("orders").insert_one({"_id": 1})

    tool = mcp._tool_manager.get_tool("db_delete_many")
    import json

    out = json.loads(await tool.fn(DecliningContext(), collection="orders", filter={}))
    assert out["ok"] is False
    remaining = await executor._client.get_collection("orders").count_documents({})
    assert remaining == 1
