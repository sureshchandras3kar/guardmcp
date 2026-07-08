"""Opt-in compact/verbose mode for guardmcp_relationships/plan_query/context.

Default stays "full" (byte-identical to before this feature) — `verbosity`
param is additive. "compact" strips ONLY `evidence` fields (the human-readable
"how we know this" reasoning trace) recursively from the response; every
decision-relevant field (kind/confidence/role/overlap_ratio/references/etc.)
is untouched.
"""

import json

import pytest
from mcp.server.fastmcp import FastMCP

from guardmcp.core.interfaces.cost import CostEstimate, CostLevel
from guardmcp.core.models.domain import Action, Decision, DecisionStatus, Request
from guardmcp.core.pipeline import EvalResult
from guardmcp.server.tools._common import ToolContext, _strip_evidence
from guardmcp.server.tools.meta import plan_query

# ── Pure helper unit tests ───────────────────────────────────────────────────


def test_strip_evidence_removes_flat_key():
    assert _strip_evidence({"kind": "fk", "evidence": "some reasoning"}) == {"kind": "fk"}


def test_strip_evidence_recurses_into_nested_dicts_and_lists():
    data = {
        "edges": [
            {"kind": "fk", "confidence": 0.9, "evidence": "why"},
            {
                "kind": "value_overlap", "evidence": "why2",
                "to": {"field": "x", "evidence": "nested"},
            },
        ]
    }
    out = _strip_evidence(data)
    assert out == {
        "edges": [
            {"kind": "fk", "confidence": 0.9},
            {"kind": "value_overlap", "to": {"field": "x"}},
        ]
    }


def test_strip_evidence_preserves_non_evidence_keys_and_scalars():
    data = {"role": "pii", "confidence": 1.0, "values": None, "count": 0}
    assert _strip_evidence(data) == data


def test_strip_evidence_does_not_mutate_input():
    original = {"evidence": "x", "kind": "fk"}
    copy_before = dict(original)
    _strip_evidence(original)
    assert original == copy_before


def test_strip_evidence_passthrough_for_scalars_and_none():
    assert _strip_evidence("plain string") == "plain string"
    assert _strip_evidence(42) == 42
    assert _strip_evidence(None) is None


# ── Tool-level wiring: guardmcp_relationships ────────────────────────────────


class _Plugin:
    name = "mongodb"

    async def relationships(self, resources):
        return [
            {
                "from_resource": "orders", "from_field": "user_id",
                "to_resource": "users", "to_field": "_id",
                "kind": "fk", "confidence": 0.9, "evidence": "naming convention match",
            }
        ]

    async def estimate(self, req):
        return CostEstimate(estimated_cost=CostLevel.LOW)


class _Entry:
    plugin = _Plugin()


class _Registry:
    def get_active(self):
        return _Entry()


class _Pipeline:
    _registry = _Registry()
    _policies = None

    async def discover_collections(self, agent):
        return ["orders", "users"]

    async def describe_collection(self, agent, collection):
        return {"fields": {"status": "string"}}

    def evaluate_capability(self, agent, resource, capability, request=None):
        return EvalResult(
            request=Request(agent=agent, collection=resource, action=Action.FIND, params={}),
            decision=Decision(status=DecisionStatus.ALLOWED, reason="ok"),
            policy=None,
        )


def _register():
    mcp = FastMCP("test")
    ctx = ToolContext(
        get_pipeline=lambda: _Pipeline(), get_agent=lambda: "claude", get_settings=lambda: None,
    )
    plan_query.register(mcp, ctx)
    return mcp


async def _call(mcp, name, **kw):
    tool = mcp._tool_manager.get_tool(name)
    return json.loads(await tool.fn(**kw))


@pytest.mark.asyncio
async def test_relationships_full_mode_keeps_evidence_by_default():
    mcp = _register()
    out = await _call(mcp, "guardmcp_relationships")
    edge = out["data"]["relationships"]["edges"][0]
    assert edge["evidence"] == "naming convention match"


@pytest.mark.asyncio
async def test_relationships_compact_mode_strips_evidence_keeps_signal():
    mcp = _register()
    out = await _call(mcp, "guardmcp_relationships", verbosity="compact")
    edge = out["data"]["relationships"]["edges"][0]
    assert "evidence" not in edge
    assert edge["kind"] == "fk" and edge["confidence"] == 0.9  # decision signal intact


@pytest.mark.asyncio
async def test_plan_query_compact_mode_strips_evidence():
    mcp = _register()
    out = await _call(mcp, "guardmcp_plan_query", intent="show orders", verbosity="compact")
    # No evidence key anywhere in the (small) response.
    assert "evidence" not in json.dumps(out["data"])


@pytest.mark.asyncio
async def test_context_compact_mode_strips_evidence_from_all_blocks():
    mcp = _register()
    out = await _call(mcp, "guardmcp_context", intent="show orders", verbosity="compact")
    assert "evidence" not in json.dumps(out["data"])


@pytest.mark.asyncio
async def test_context_full_mode_is_default_and_unchanged():
    mcp = _register()
    full = await _call(mcp, "guardmcp_context", intent="show orders")
    explicit_full = await _call(mcp, "guardmcp_context", intent="show orders", verbosity="full")
    # Compare structure/keys, not full equality: each call builds a fresh
    # RelationshipResolver, so `generated_at` legitimately differs per call.
    assert set(full["data"].keys()) == set(explicit_full["data"].keys())
    edge = full["data"]["relationships"]["edges"][0]
    explicit_edge = explicit_full["data"]["relationships"]["edges"][0]
    assert edge["evidence"] == explicit_edge["evidence"] == "naming convention match"
