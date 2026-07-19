"""Opt-in "_meta-only" repeat-call optimization for guardmcp_context's semantics
block (Option B): the agent echoes back the stamp it got last time
(`known_stamps`); if a collection's semantics are unchanged, the server returns
a compact `{"unchanged_since": stamp}` instead of the full field dict — the
agent already has the real data from its own conversation history.

Additive/backward-compatible: `known_stamps` defaults to None, in which case
`semantics` is byte-identical to before this feature (test_context_tool.py's
existing assertions still hold unchanged). `semantics_stamps` is a new sibling
key, always present, that the agent should remember and pass back next call.
"""

import json

import pytest
from mcp.server.fastmcp import FastMCP

from guardmcp.server.tools._common import ToolContext
from guardmcp.server.tools.meta import plan_query
from guardmcp.server.tools.meta.plan_query import _semantics_stamp

from .test_context_tool import _SEMANTICS, _Pipeline


def _register(pipeline):
    mcp = FastMCP("test")
    ctx = ToolContext(
        get_pipeline=lambda: pipeline, get_agent=lambda: "claude", get_settings=lambda: None,
    )
    plan_query.register(mcp, ctx)
    return mcp


async def _call_context(mcp, **kw):
    tool = mcp._tool_manager.get_tool("guardmcp_context")
    return json.loads(await tool.fn(**kw))


# ── Pure stamp helper ────────────────────────────────────────────────────────


def test_stamp_deterministic_for_same_fields():
    fields = {"_id": {"role": "primary_identifier"}, "user_id": {"role": "foreign_identifier"}}
    assert _semantics_stamp(fields) == _semantics_stamp(dict(fields))


def test_stamp_deterministic_regardless_of_key_order():
    a = {"_id": {"role": "primary_identifier"}, "user_id": {"role": "foreign_identifier"}}
    b = {"user_id": {"role": "foreign_identifier"}, "_id": {"role": "primary_identifier"}}
    assert _semantics_stamp(a) == _semantics_stamp(b)


def test_stamp_differs_when_fields_change():
    a = {"_id": {"role": "primary_identifier"}}
    b = {"_id": {"role": "primary_identifier"}, "user_id": {"role": "foreign_identifier"}}
    assert _semantics_stamp(a) != _semantics_stamp(b)


# ── Tool wiring ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_known_stamps_returns_full_semantics_unchanged():
    # Backward-compat: default behavior identical to before this feature.
    pipeline = _Pipeline()
    mcp = _register(pipeline)
    out = await _call_context(mcp, intent="show active orders")
    assert out["data"]["semantics"]["order"] == _SEMANTICS["order"]
    # New sibling key always present, so the agent has something to echo back.
    assert out["data"]["semantics_stamps"]["order"] == _semantics_stamp(_SEMANTICS["order"])


@pytest.mark.asyncio
async def test_matching_known_stamp_returns_compact_form():
    pipeline = _Pipeline()
    mcp = _register(pipeline)
    first = await _call_context(mcp, intent="show active orders")
    stamp = first["data"]["semantics_stamps"]["order"]

    second = await _call_context(
        mcp, intent="show active orders", known_stamps={"order": stamp}
    )
    assert second["data"]["semantics"]["order"] == {"unchanged_since": stamp}


@pytest.mark.asyncio
async def test_stale_or_wrong_known_stamp_falls_back_to_full():
    pipeline = _Pipeline()
    mcp = _register(pipeline)
    out = await _call_context(
        mcp, intent="show active orders", known_stamps={"order": "wrong-stamp"}
    )
    assert out["data"]["semantics"]["order"] == _SEMANTICS["order"]


@pytest.mark.asyncio
async def test_unknown_collection_in_known_stamps_is_ignored():
    pipeline = _Pipeline()
    mcp = _register(pipeline)
    out = await _call_context(
        mcp, intent="show active orders", known_stamps={"some_other_collection": "x"}
    )
    assert out["data"]["semantics"]["order"] == _SEMANTICS["order"]
