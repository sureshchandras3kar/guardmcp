"""Section C — guardmcp_* meta tools, real MongoDB."""

from __future__ import annotations

import pytest
import pytest_asyncio

from .conftest import build_pipeline, readwrite_masked_policy
from .helpers import call, make_mcp


class _Settings:
    def __init__(self, policy_path, mongodb_database="default_db"):
        self.policy_path = policy_path
        self.mongodb_database = mongodb_database
        self.rate_limit_rps = 0
        self.rate_limit_burst = 0
        self.protocol_version = None


@pytest_asyncio.fixture
async def env(tmp_path, mongo_uri, db_name):
    pipeline, registry, _ = build_pipeline(
        tmp_path, mongo_uri, db_name,
        readwrite_masked_policy(
            collections_allow=["users", "orders"], mask_fields=["ssn"],
            approval_high=False, approval_critical=False,
        ),
    )
    executor = registry.get("default").executor
    await executor._client.get_collection("users").insert_many(
        [
            {"name": "a", "status": "active", "ssn": "1"},
            {"name": "b", "status": "active", "ssn": "2"},
        ]
    )
    settings = _Settings(tmp_path / "policy.yaml", mongodb_database=db_name)
    mcp = make_mcp(pipeline, settings=settings)
    return mcp, pipeline, registry, settings


@pytest.mark.asyncio
async def test_status_reflects_active_connection_and_database(env):
    mcp, pipeline, _, _ = env
    out = await call(mcp, "guardmcp_status")
    assert out["ok"] is True
    stats = out["data"]["stats"]
    assert stats["connection"] == "default"
    assert stats["policy_loaded"] is True
    assert stats["mode"] == "readwrite"


@pytest.mark.asyncio
async def test_capabilities(env):
    mcp, _, _, _ = env
    out = await call(mcp, "guardmcp_capabilities")
    assert out["ok"] is True
    assert out["data"]["backend"] == "mongodb"


@pytest.mark.asyncio
async def test_plan_dry_run_never_executes(env):
    mcp, _, registry, _ = env
    out = await call(
        mcp, "guardmcp_plan", collection="users", action="delete_many", filter={}
    )
    assert out["ok"] is True
    executor = registry.get("default").executor
    count = await executor._client.get_collection("users").count_documents({})
    assert count == 2  # plan never executes


@pytest.mark.asyncio
async def test_plan_query(env):
    mcp, _, _, _ = env
    out = await call(mcp, "guardmcp_plan_query", intent="show active users")
    assert out["ok"] is True
    assert "ambiguity" in out["data"]
    assert "relationships" in out["data"]


@pytest.mark.asyncio
async def test_relationships(env):
    mcp, _, _, _ = env
    out = await call(mcp, "guardmcp_relationships")
    assert out["ok"] is True
    assert "relationships" in out["data"]
    assert "cross_db_edges" in out["data"]


@pytest.mark.asyncio
async def test_context_compact_strips_evidence(env):
    mcp, _, _, _ = env
    out = await call(mcp, "guardmcp_context", intent="show users", verbosity="compact")
    assert out["ok"] is True
    import json as _json

    assert "evidence" not in _json.dumps(out["data"])


@pytest.mark.asyncio
async def test_context_known_stamps_repeat_call(env):
    mcp, _, _, _ = env
    first = await call(mcp, "guardmcp_context", intent="show users")
    assert first["ok"] is True
    stamps = first["data"]["semantics_stamps"]
    if stamps:
        name, stamp = next(iter(stamps.items()))
        second = await call(
            mcp, "guardmcp_context", intent="show users", known_stamps={name: stamp}
        )
        assert second["data"]["semantics"][name] == {"unchanged_since": stamp}


@pytest.mark.asyncio
async def test_explain_policy(env):
    mcp, _, _, _ = env
    out = await call(
        mcp, "guardmcp_explain_policy", agent="claude", collection="users", action="find"
    )
    assert out["ok"] is True


@pytest.mark.asyncio
async def test_simulate_policy(env):
    mcp, _, _, _ = env
    out = await call(
        mcp, "guardmcp_simulate_policy",
        request={"agent": "claude", "collection": "users", "action": "find"},
        proposed_policy="agent: claude\nmode: readonly\ncollections:\n  allow: []\n",
    )
    assert out["ok"] is True
    assert out["data"]["proposed_decision"] == "denied"


@pytest.mark.asyncio
async def test_setup_readwrite_mode_grants_write_actions(env, tmp_path):
    mcp, _, _, settings = env
    out = await call(
        mcp, "guardmcp_setup",
        answers={"agent_name": "claude", "mode": "readwrite", "collections_allow": "*"},
    )
    assert out["ok"] is True
    written = settings.policy_path.read_text()
    assert "insert_one" in written or "delete_many" in written
