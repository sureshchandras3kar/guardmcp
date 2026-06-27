"""
Tests for guardmcp_explain_policy (Feature 2). Drives the REAL tool through a
FastMCP registration so the trace comes from the same evaluate() that authorizes.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP
from mongomock_motor import AsyncMongoMockClient

from guardmcp.core.approval.store import ApprovalStore
from guardmcp.core.audit.logger import AuditLogger
from guardmcp.core.pipeline import GuardPipeline
from guardmcp.core.policy.engine import PolicyEngine
from guardmcp.core.policy.models import (
    ActionPolicy,
    ApprovalPolicy,
    CollectionPolicy,
    Policy,
)
from guardmcp.core.risk.engine import RiskEngine
from guardmcp.eval.runner import _InlineLoader
from guardmcp.plugins.mongodb.executor import MongoExecutor
from guardmcp.server import tools as tools_mod


def _client():
    real = AsyncMongoMockClient()

    class _C:
        def get_collection(self, name):
            return real["t"][name]

        def get_db(self):
            return real["t"]

        async def list_collection_names(self):
            return await real["t"].list_collection_names()

        async def list_databases(self):  # noqa: RUF029
            return [{"name": "t", "sizeOnDisk": 0}]

        def close(self):
            pass

    return _C()


def _pipeline(policy: Policy, tmp_path: Path) -> GuardPipeline:
    return GuardPipeline(
        policy_loader=_InlineLoader(policy),
        policy_engine=PolicyEngine(),
        risk_engine=RiskEngine(),
        audit_logger=AuditLogger(tmp_path / "audit.jsonl"),
        approval_store=ApprovalStore(timeout_seconds=0.01),
        executor=MongoExecutor(_client(), schema_cache_ttl=0),
    )


def _tool(pipeline):
    mcp = FastMCP("test")
    tools_mod.register_tools(mcp, lambda: pipeline, lambda: "claude", lambda: None)
    return mcp._tool_manager.get_tool("guardmcp_explain_policy")


async def _call(tool, **kw):
    return json.loads(await tool.fn(**kw))


def _base(**kw) -> Policy:
    defaults = dict(
        agent="claude",
        mode="readwrite",
        collections=CollectionPolicy(allow=["users"]),
        actions=ActionPolicy(),
        approval=ApprovalPolicy(),
    )
    defaults.update(kw)
    return Policy(**defaults)


@pytest.mark.asyncio
async def test_explain_allowed(tmp_path):
    tool = _tool(_pipeline(_base(), tmp_path))
    res = await _call(tool, agent="claude", collection="users", action="find")
    assert res["ok"]
    d = res["data"]
    assert d["decision"] == "ALLOWED"
    assert "policy" in d["evaluation_trace"]
    assert any(r["rule"] == "default_allow" for r in d["matched_rules"])


@pytest.mark.asyncio
async def test_explain_denied_collection(tmp_path):
    pol = _base(collections=CollectionPolicy(allow=["users"], deny=["secrets"]))
    tool = _tool(_pipeline(pol, tmp_path))
    res = await _call(tool, agent="claude", collection="secrets", action="find")
    d = res["data"]
    assert d["decision"] == "DENIED"
    assert any(r["rule"] == "collection_access" for r in d["matched_rules"])
    assert "secrets" in d["reason"]
    assert d["code"] is not None


@pytest.mark.asyncio
async def test_explain_approval_required(tmp_path):
    # aggregate is HIGH risk and NOT scope-sensitive (empty filter won't escalate
    # it to CRITICAL the way update/delete do).
    pol = _base(approval=ApprovalPolicy(high=True))
    tool = _tool(_pipeline(pol, tmp_path))
    res = await _call(tool, agent="claude", collection="users", action="aggregate")
    d = res["data"]
    assert d["decision"] == "APPROVAL_REQUIRED"
    assert d["approval_required"] is True
    assert d["risk"] == "HIGH"
    assert any(r["rule"] == "approval_high" for r in d["matched_rules"])


@pytest.mark.asyncio
async def test_explain_temporal_expired(tmp_path):
    past = datetime.now(UTC) - timedelta(days=1)
    pol = _base(not_after=past)
    tool = _tool(_pipeline(pol, tmp_path))
    res = await _call(tool, agent="claude", collection="users", action="find")
    d = res["data"]
    assert d["decision"] == "DENIED"
    assert "pipeline" in d["evaluation_trace"]
    assert any(r["rule"] == "temporal_window" for r in d["matched_rules"])


@pytest.mark.asyncio
async def test_explain_unknown_action(tmp_path):
    tool = _tool(_pipeline(_base(), tmp_path))
    res = await _call(tool, agent="claude", collection="users", action="frobnicate")
    assert res["ok"] is False
    assert res["error"]["code"] == "VALIDATION"


@pytest.mark.asyncio
async def test_explain_role_inherited(tmp_path):
    """A merged (inherited) policy is what gets evaluated; trace reflects it."""
    # Build a resolved policy as the loader would (readonly base merged with
    # an allow widening) — here we just assert the effective merged policy denies
    # a write because the merged mode stays readonly.
    merged = _base(mode="readonly", actions=ActionPolicy(allow=["find", "count"]))
    tool = _tool(_pipeline(merged, tmp_path))
    res = await _call(tool, agent="claude", collection="users", action="delete_one")
    d = res["data"]
    assert d["decision"] == "DENIED"
    assert any(r["rule"] == "readonly_mode" for r in d["matched_rules"])
