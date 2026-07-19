"""guardmcp_setup — regression for a real bug found reviewing the new-user
onboarding flow: mode="readwrite" answers produced a policy whose
actions.allow was HARDCODED to read-only actions, so a brand-new user picking
"readwrite" in the wizard got a policy that silently behaved like readonly
(every write denied via ACTION_NOT_ALLOWED, before risk/approval ever runs)
until they hand-edited the generated YAML.
"""

import json

import pytest
import yaml
from mcp.server.fastmcp import FastMCP

from guardmcp.core.models.domain import WRITE_ACTIONS
from guardmcp.server.tools._common import ToolContext
from guardmcp.server.tools.meta import setup as setup_tool


class _Settings:
    def __init__(self, policy_path):
        self.policy_path = policy_path


class _Loader:
    def __init__(self):
        self.load_calls = 0

    def load(self):
        self.load_calls += 1


class _Pipeline:
    def __init__(self):
        self._policies = _Loader()


def _register(tmp_path):
    mcp = FastMCP("test")
    settings = _Settings(tmp_path / "policy.yaml")
    pipeline = _Pipeline()
    ctx = ToolContext(
        get_pipeline=lambda: pipeline, get_agent=lambda: "claude", get_settings=lambda: settings,
    )
    setup_tool.register(mcp, ctx)
    return mcp, settings


async def _call(mcp, **kwargs):
    tool = mcp._tool_manager.get_tool("guardmcp_setup")
    return json.loads(await tool.fn(**kwargs))


@pytest.mark.asyncio
async def test_no_answers_returns_survey(tmp_path):
    mcp, _ = _register(tmp_path)
    out = await _call(mcp)
    assert out["ok"] is True
    assert out["data"]["setup_required"] is True


@pytest.mark.asyncio
async def test_readwrite_mode_actually_grants_write_actions(tmp_path):
    mcp, settings = _register(tmp_path)
    out = await _call(
        mcp,
        answers={"agent_name": "claude", "mode": "readwrite", "collections_allow": "*"},
    )
    assert out["ok"] is True

    written = yaml.safe_load(settings.policy_path.read_text())
    allow = set(written["actions"]["allow"])
    write_action_values = {a.value for a in WRITE_ACTIONS}

    # The bug: previously `allow` was hardcoded to read-only actions even when
    # mode == "readwrite", so no write action was ever in the list.
    assert write_action_values & allow, (
        f"readwrite mode must grant at least some write actions; got {sorted(allow)}"
    )
    # And every actual write action must be included (not a partial/stale list).
    assert write_action_values <= allow


@pytest.mark.asyncio
async def test_readonly_mode_grants_no_write_actions(tmp_path):
    mcp, settings = _register(tmp_path)
    out = await _call(
        mcp, answers={"agent_name": "claude", "mode": "readonly", "collections_allow": "*"}
    )
    assert out["ok"] is True

    written = yaml.safe_load(settings.policy_path.read_text())
    allow = set(written["actions"]["allow"])
    write_action_values = {a.value for a in WRITE_ACTIONS}
    assert not (write_action_values & allow)  # readonly must stay writes-free


@pytest.mark.asyncio
async def test_readwrite_still_includes_read_actions(tmp_path):
    mcp, settings = _register(tmp_path)
    await _call(
        mcp, answers={"agent_name": "claude", "mode": "readwrite", "collections_allow": "*"}
    )
    written = yaml.safe_load(settings.policy_path.read_text())
    allow = set(written["actions"]["allow"])
    assert {"find", "count", "aggregate"} <= allow
