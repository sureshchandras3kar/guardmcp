"""
Tests for guardmcp_simulate_policy (Feature 3). Verifies decision flips, the
human-readable diff, and the security-impact heuristic — all from the REAL
evaluate() via policy_override (no second evaluator).
"""

import json
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP
from mongomock_motor import AsyncMongoMockClient

from guardmcp.core.approval.store import ApprovalStore
from guardmcp.core.audit.logger import AuditLogger
from guardmcp.core.pipeline import GuardPipeline
from guardmcp.core.policy.engine import PolicyEngine
from guardmcp.core.policy.models import (
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
    return mcp._tool_manager.get_tool("guardmcp_simulate_policy")


async def _call(tool, **kw):
    return json.loads(await tool.fn(**kw))


def _pol_dict(**over):
    base = {
        "agent": "claude",
        "mode": "readonly",
        "collections": {"allow": ["users"]},
    }
    base.update(over)
    return base


@pytest.mark.asyncio
async def test_readonly_to_readwrite_flips_decision(tmp_path):
    current = Policy(
        agent="claude",
        mode="readonly",
        collections=CollectionPolicy(allow=["users"]),
    )
    tool = _tool(_pipeline(current, tmp_path))
    proposed = _pol_dict(mode="readwrite")
    res = await _call(
        tool,
        request={"agent": "claude", "collection": "users", "action": "update_one"},
        proposed_policy=proposed,
    )
    assert res["ok"]
    d = res["data"]
    assert d["current_decision"] == "denied"
    assert d["proposed_decision"] in ("allowed", "approval_required")
    assert d["decision_changed"] is True
    assert any("readonly" in r.lower() for r in d["changed_rules"])
    assert d["impact"]["security"] == "HIGH"
    assert d["impact"]["behavior_change"] is True


@pytest.mark.asyncio
async def test_identical_policies_no_change(tmp_path):
    current = Policy(
        agent="claude",
        mode="readonly",
        collections=CollectionPolicy(allow=["users"]),
    )
    tool = _tool(_pipeline(current, tmp_path))
    res = await _call(
        tool,
        request={"agent": "claude", "collection": "users", "action": "find"},
        proposed_policy=_pol_dict(),
    )
    d = res["data"]
    assert d["decision_changed"] is False
    assert d["changed_rules"] == []
    assert d["impact"]["security"] == "LOW"
    assert d["impact"]["behavior_change"] is False


@pytest.mark.asyncio
async def test_widening_collections_is_high(tmp_path):
    current = Policy(
        agent="claude",
        mode="readonly",
        collections=CollectionPolicy(allow=["users"]),
    )
    tool = _tool(_pipeline(current, tmp_path))
    proposed = _pol_dict(collections={"allow": ["users", "orders"]})
    res = await _call(
        tool,
        request={"agent": "claude", "collection": "orders", "action": "find"},
        proposed_policy=proposed,
    )
    d = res["data"]
    assert any("orders" in r and "collections.allow" in r for r in d["changed_rules"])
    assert d["impact"]["security"] == "HIGH"
    assert d["current_decision"] == "denied"
    assert d["proposed_decision"] == "allowed"


@pytest.mark.asyncio
async def test_narrowing_is_low(tmp_path):
    current = Policy(
        agent="claude",
        mode="readonly",
        collections=CollectionPolicy(allow=["users", "orders"]),
    )
    tool = _tool(_pipeline(current, tmp_path))
    proposed = _pol_dict(collections={"allow": ["users"]})
    res = await _call(
        tool,
        request={"agent": "claude", "collection": "users", "action": "find"},
        proposed_policy=proposed,
    )
    d = res["data"]
    assert any("Removed orders" in r for r in d["changed_rules"])
    assert d["impact"]["security"] == "LOW"


@pytest.mark.asyncio
async def test_yaml_string_policy_and_mask_diff(tmp_path):
    current = Policy(
        agent="claude",
        mode="readwrite",
        collections=CollectionPolicy(allow=["users"]),
    )
    tool = _tool(_pipeline(current, tmp_path))
    proposed_yaml = (
        "agent: claude\nmode: readwrite\ncollections:\n  allow: [users]\nmask_fields: [ssn]\n"
    )
    res = await _call(
        tool,
        request={"agent": "claude", "collection": "users", "action": "find"},
        proposed_policy=proposed_yaml,
    )
    d = res["data"]
    assert any("Now masks: ssn" in r for r in d["changed_rules"])


@pytest.mark.asyncio
async def test_current_defaults_to_loaded_policy(tmp_path):
    current = Policy(
        agent="claude",
        mode="readonly",
        collections=CollectionPolicy(allow=["users"]),
    )
    tool = _tool(_pipeline(current, tmp_path))
    # current_policy omitted -> uses the loaded policy.
    res = await _call(
        tool,
        request={"agent": "claude", "collection": "users", "action": "update_one"},
        proposed_policy=_pol_dict(mode="readwrite"),
    )
    d = res["data"]
    assert d["current_decision"] == "denied"
    assert d["decision_changed"] is True


@pytest.mark.asyncio
async def test_invalid_proposed_policy(tmp_path):
    current = Policy(agent="claude", collections=CollectionPolicy(allow=["users"]))
    tool = _tool(_pipeline(current, tmp_path))
    res = await _call(
        tool,
        request={"agent": "claude", "collection": "users", "action": "find"},
        proposed_policy={"agent": "claude", "mode": "bogus"},
    )
    assert res["ok"] is False
    assert res["error"]["code"] == "VALIDATION"


@pytest.mark.asyncio
async def test_unknown_action(tmp_path):
    current = Policy(agent="claude", collections=CollectionPolicy(allow=["users"]))
    tool = _tool(_pipeline(current, tmp_path))
    res = await _call(
        tool,
        request={"agent": "claude", "collection": "users", "action": "frob"},
        proposed_policy=_pol_dict(),
    )
    assert res["ok"] is False
    assert res["error"]["code"] == "VALIDATION"
