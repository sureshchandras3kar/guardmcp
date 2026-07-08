import json

import pytest
from mcp.server.fastmcp import FastMCP

from guardmcp.core.interfaces.cost import CostEstimate, CostLevel
from guardmcp.core.models.domain import Action, Decision, DecisionStatus, Request
from guardmcp.core.pipeline import EvalResult
from guardmcp.server.tools._common import ToolContext
from guardmcp.server.tools.meta import plan_query

# 5 collections, "order" is most-connected (touches both edges) so with
# top_n=1 only "order" should get a semantics lookup.
_COLLECTIONS = ["user", "order", "product", "review", "cart"]
_SCHEMA_FIELDS = {
    "user": {"status": "string"},
    "order": {"status": "string"},
    "product": {"status": "string"},
    "review": {"status": "string"},
    "cart": {"status": "string"},
}
_SEMANTICS = {
    "user": {"_id": {"role": "primary_identifier"}},
    "order": {"_id": {"role": "primary_identifier"}, "user_id": {"role": "foreign_identifier"}},
    "product": {"_id": {"role": "primary_identifier"}},
    "review": {"_id": {"role": "primary_identifier"}},
    "cart": {"_id": {"role": "primary_identifier"}},
}


class _Executor:
    async def collection_indexes(self, collection):
        return [{"name": "status_1", "key": [("status", 1)]}]


class _Plugin:
    name = "mongodb"

    def __init__(self):
        self._executor = _Executor()

    async def relationships(self, resources):
        return [
            {
                "from_resource": "user", "from_field": "_id",
                "to_resource": "order", "to_field": "user_id",
                "kind": "fk", "confidence": 0.9, "evidence": "test",
            },
            {
                "from_resource": "order", "from_field": "_id",
                "to_resource": "product", "to_field": "order_id",
                "kind": "fk", "confidence": 0.9, "evidence": "test",
            },
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
    _policies = None  # no databases_allow -> cross_db block degrades to []

    def __init__(self):
        self.describe_calls: list[str] = []

    async def discover_collections(self, agent):
        return _COLLECTIONS

    async def describe_collection(self, agent, collection):
        self.describe_calls.append(collection)
        return {"fields": _SCHEMA_FIELDS[collection], "semantics": _SEMANTICS[collection]}

    def evaluate_capability(self, agent, resource, capability, request=None):
        return EvalResult(
            request=Request(agent=agent, collection=resource, action=Action.FIND, params={}),
            decision=Decision(status=DecisionStatus.ALLOWED, reason="ok"),
            policy=None,
        )


def _register(pipeline):
    mcp = FastMCP("test")
    ctx = ToolContext(
        get_pipeline=lambda: pipeline,
        get_agent=lambda: "claude",
        get_settings=lambda: None,
    )
    plan_query.register(mcp, ctx)
    return mcp


@pytest.mark.asyncio
async def test_context_bundles_plan_relationships_and_semantics():
    pipeline = _Pipeline()
    mcp = _register(pipeline)
    tool = mcp._tool_manager.get_tool("guardmcp_context")
    out = json.loads(await tool.fn(intent="show active orders"))

    assert out["ok"] is True
    data = out["data"]
    # Same shape as guardmcp_plan_query (ambiguity/relationships/plans/notes).
    assert "ambiguity" in data and "relationships" in data and "plans" in data
    # Additive cross-db keys (same pattern as guardmcp_relationships).
    assert data["cross_db_edges"] == []
    assert data["cross_db_paths"] == []
    # Semantics present, capped to the most-connected collections.
    assert "semantics" in data
    assert "order" in data["semantics"]  # degree 2, must be included


@pytest.mark.asyncio
async def test_semantics_capped_to_top_n_by_centrality():
    pipeline = _Pipeline()
    mcp = _register(pipeline)
    tool = mcp._tool_manager.get_tool("guardmcp_context")
    await tool.fn(intent="show active orders")

    # describe_collection is called once for plan()'s own resource resolution
    # (whichever collection the intent picks) plus once per top-N centrality
    # pick — never once per ALL 5 accessible collections.
    assert len(set(pipeline.describe_calls)) < len(_COLLECTIONS)


@pytest.mark.asyncio
async def test_semantics_lookup_failure_for_one_collection_never_breaks_the_bundle():
    # "order" (the chosen resource, needed by plan() itself) still succeeds;
    # the OTHER top-N picks ("product", "user") fail — the semantics step must
    # degrade per-collection, not blow up the whole guardmcp_context call.
    class _PartiallyBrokenPipeline(_Pipeline):
        async def describe_collection(self, agent, collection):
            if collection != "order":
                raise RuntimeError("backend down")
            return await super().describe_collection(agent, collection)

    pipeline = _PartiallyBrokenPipeline()
    mcp = _register(pipeline)
    tool = mcp._tool_manager.get_tool("guardmcp_context")
    out = json.loads(await tool.fn(intent="show active orders"))

    assert out["ok"] is True
    assert out["data"]["semantics"] == {"order": _SEMANTICS["order"]}
