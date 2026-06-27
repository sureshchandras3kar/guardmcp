"""Tests for the MCP tool-design overhaul: dual names, envelopes, plan, capabilities."""

import json

import pytest
import pytest_asyncio
from mcp.server.fastmcp import FastMCP
from mongomock_motor import AsyncMongoMockClient

from guardmcp.core.approval.store import ApprovalStore
from guardmcp.core.audit.logger import AuditLogger
from guardmcp.core.interfaces.capability import Capability
from guardmcp.core.pipeline import GuardPipeline
from guardmcp.core.policy.engine import PolicyEngine
from guardmcp.core.policy.loader import PolicyLoader
from guardmcp.core.risk.engine import RiskEngine
from guardmcp.plugins.mongodb.executor import MongoExecutor
from guardmcp.server import tools as tools_mod
from guardmcp.server.responses import (
    ErrorCode,
    err,
    from_pipeline_result,
    ok,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


class _FakeManager:
    def __init__(self):
        self.names: list[str] = []
        self.annotations: dict = {}

    def tool(self, *, name=None, description=None, annotations=None, **kw):
        def deco(fn):
            tool_name = name or getattr(fn, "__name__", None)
            self.names.append(tool_name)
            self.annotations[tool_name] = annotations
            return fn

        return deco


def _register_into_fake():
    fake = _FakeManager()
    tools_mod.register_tools(fake, lambda: None, lambda: "a", lambda: None)
    return fake


def _make_client():
    real = AsyncMongoMockClient()

    class _Client:
        def get_collection(self, name):
            return real["testdb"][name]

        def get_db(self):
            return real["testdb"]

        async def list_collection_names(self):
            return await real["testdb"].list_collection_names()

        async def list_databases(self):  # noqa: RUF029
            return [{"name": "testdb", "sizeOnDisk": 0}]

        def close(self):
            pass

    return _Client(), real


@pytest_asyncio.fixture
async def rw_pipeline(tmp_path):
    pol = tmp_path / "policy.yaml"
    pol.write_text(
        """
agent: test-agent
mode: readwrite
collections:
  allow:
    - users
actions:
  allow:
    - find
    - count
    - aggregate
    - delete_many
    - delete_one
    - update_many
mask_fields:
  - password
approval:
  high: true
  critical: true
"""
    )
    loader = PolicyLoader(pol)
    loader.load()
    client, real = _make_client()
    # seed
    await real["testdb"]["users"].insert_many(
        [
            {"name": "a", "status": "active"},
            {"name": "b", "status": "active"},
            {"name": "c", "status": "inactive"},
        ]
    )
    pipeline = GuardPipeline(
        policy_loader=loader,
        policy_engine=PolicyEngine(),
        risk_engine=RiskEngine(),
        audit_logger=AuditLogger(tmp_path / "audit.jsonl"),
        approval_store=ApprovalStore(timeout_seconds=1.0),
        executor=MongoExecutor(client),
    )
    return pipeline, real


def _get_tool(pipeline, name):
    """Register real tools into a FastMCP and fetch the callable for `name`."""
    mcp = FastMCP("test")
    tools_mod.register_tools(mcp, lambda: pipeline, lambda: "test-agent", lambda: None)
    return mcp._tool_manager.get_tool(name)


async def _call(tool, **kwargs):
    return json.loads(await tool.fn(**kwargs))


# ── 1. Dual registration ───────────────────────────────────────────────────────


def test_both_db_and_mongodb_names_registered():
    fake = _register_into_fake()
    for primary, alias in [
        ("db_find", "mongodb_find"),
        ("db_count", "mongodb_count"),
        ("db_aggregate", "mongodb_aggregate"),
        ("db_delete_many", "mongodb_delete_many"),
        ("db_create_index", "mongodb_create_index"),
        ("db_list_collections", "mongodb_list_collections"),
    ]:
        assert primary in fake.names, primary
        assert alias in fake.names, alias
    # meta tools keep their names
    assert "guardmcp_status" in fake.names
    assert "guardmcp_plan" in fake.names
    assert "guardmcp_capabilities" in fake.names
    assert "guardmcp_explain_policy" in fake.names
    assert "guardmcp_simulate_policy" in fake.names


def test_annotations_applied_or_skipped():
    fake = _register_into_fake()
    if tools_mod.ANNOTATIONS_SUPPORTED:
        assert fake.annotations["db_find"].readOnlyHint is True
        assert fake.annotations["db_delete_many"].destructiveHint is True
    else:
        # Skipped gracefully — still registered, annotations None.
        assert fake.annotations["db_find"] is None
        assert "db_find" in fake.names


# ── 2 & 5. Envelope + error mapping ─────────────────────────────────────────────


def test_ok_envelope_shape():
    payload = json.loads(ok({"x": 1}, source="t"))
    assert payload["ok"] is True
    assert payload["data"] == {"x": 1}
    assert payload["error"] is None
    assert payload["meta"] == {"source": "t"}


def test_err_envelope_shape():
    payload = json.loads(err(ErrorCode.VALIDATION, "bad", retryable=False, suggested_action="fix"))
    assert payload["ok"] is False
    assert payload["data"] is None
    assert payload["error"]["code"] == "VALIDATION"
    assert payload["error"]["message"] == "bad"
    assert payload["error"]["retryable"] is False
    assert payload["error"]["suggested_action"] == "fix"


def test_from_pipeline_result_success():
    p = json.loads(from_pipeline_result({"status": "success", "data": [1, 2]}))
    assert p["ok"] is True and p["data"] == [1, 2]


def test_from_pipeline_result_denied_readonly():
    p = json.loads(
        from_pipeline_result(
            {"status": "denied", "reason": "action 'delete_one' is blocked in readonly mode."}
        )
    )
    assert p["error"]["code"] == "READONLY"
    assert p["error"]["retryable"] is False


def test_from_pipeline_result_denied_collection():
    p = json.loads(
        from_pipeline_result(
            {
                "status": "denied",
                "reason": "collection 'x' is not in the allowed list. Allowed: ['y'].",
            }
        )
    )
    assert p["error"]["code"] == "COLLECTION_NOT_ALLOWED"


def test_from_pipeline_result_error_backend():
    p = json.loads(from_pipeline_result({"status": "error", "reason": "boom"}))
    assert p["error"]["code"] == "BACKEND_ERROR"
    assert p["error"]["retryable"] is True


def test_from_pipeline_result_rate_limited():
    p = json.loads(
        from_pipeline_result({"status": "error", "reason": "rate limit exceeded for agent"})
    )
    assert p["error"]["code"] == "RATE_LIMITED"
    assert p["error"]["retryable"] is True


# ── 3. guardmcp_plan dry-run ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_plan_delete_many_empty_filter_critical_no_execution(rw_pipeline):
    pipeline, real = rw_pipeline
    before = await real["testdb"]["users"].count_documents({})
    plan_tool = _get_tool(pipeline, "guardmcp_plan")
    payload = await _call(plan_tool, collection="users", action="delete_many", filter={})
    assert payload["ok"] is True
    data = payload["data"]
    assert data["risk"] == "CRITICAL"
    assert data["approval_required"] is True
    assert data["decision"] == "approval_required"
    assert data["would_affect"] == before  # whole collection
    # NOT executed — count unchanged
    after = await real["testdb"]["users"].count_documents({})
    assert after == before == 3


@pytest.mark.asyncio
async def test_plan_includes_cost_block_unknown_without_plugin(rw_pipeline):
    # No registry/plugin is wired into this pipeline, so cost estimation degrades
    # to UNKNOWN + warning — and the plan STILL succeeds (estimation never fails
    # the plan).
    pipeline, _ = rw_pipeline
    plan_tool = _get_tool(pipeline, "guardmcp_plan")
    payload = await _call(plan_tool, collection="users", action="find", filter={"name": "a"})
    assert payload["ok"] is True
    data = payload["data"]
    assert "cost" in data
    assert data["cost"]["estimated_cost"] == "UNKNOWN"
    assert data["cost"]["warnings"]  # non-empty warning explaining why
    # raw explain shapes never leak into the cost block
    assert "winningPlan" not in json.dumps(data["cost"])
    assert "executionStats" not in json.dumps(data["cost"])


@pytest.mark.asyncio
async def test_plan_unknown_action_validation(rw_pipeline):
    pipeline, _ = rw_pipeline
    plan_tool = _get_tool(pipeline, "guardmcp_plan")
    payload = await _call(plan_tool, collection="users", action="nonsense")
    assert payload["ok"] is False
    assert payload["error"]["code"] == "VALIDATION"


# ── 4. guardmcp_capabilities ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_capabilities_returns_backend_and_collections(rw_pipeline):
    pipeline, _ = rw_pipeline
    cap_tool = _get_tool(pipeline, "guardmcp_capabilities")
    payload = await _call(cap_tool)
    assert payload["ok"] is True
    data = payload["data"]
    assert data["backend"] == "mongodb"
    assert "read" in data["supported_capabilities"]
    assert data["mode"] == "readwrite"
    assert "users" in data["collections"]
    actions = {e["action"] for e in data["collections"]["users"]}
    assert "find" in actions
    assert "delete_many" in actions  # readwrite + allowed
    assert "insert_one" not in actions  # not in actions.allow
    assert data["masked_fields"] == ["password"]


# ── 9. UNSUPPORTED_CAPABILITY ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unsupported_capability_helper(rw_pipeline):
    from guardmcp.core.models.domain import Action

    pipeline, _ = rw_pipeline

    class _FakePlugin:
        name = "limiteddb"
        supported = frozenset({Capability.READ, Capability.COUNT})  # no AGGREGATE

    class _Entry:
        plugin = _FakePlugin()

    class _Registry:
        def get_active(self):
            return _Entry()

    pipeline._registry = _Registry()
    out = tools_mod._capability_check(pipeline, Action.AGGREGATE)
    assert out is not None
    p = json.loads(out)
    assert p["error"]["code"] == "UNSUPPORTED_CAPABILITY"
    assert "limiteddb" in p["error"]["message"]
    # supported capability returns None (no error)
    assert tools_mod._capability_check(pipeline, Action.FIND) is None


@pytest.mark.asyncio
async def test_db_aggregate_unsupported_capability(rw_pipeline):
    pipeline, _ = rw_pipeline

    class _FakePlugin:
        name = "limiteddb"
        supported = frozenset({Capability.READ})

    class _Entry:
        plugin = _FakePlugin()

    class _Registry:
        def get_active(self):
            return _Entry()

        def get_arbitrary(self):  # noqa
            return None

    pipeline._registry = _Registry()
    agg = _get_tool(pipeline, "db_aggregate")
    payload = await _call(agg, collection="users", pipeline_stages=[{"$match": {}}])
    assert payload["ok"] is False
    assert payload["error"]["code"] == "UNSUPPORTED_CAPABILITY"


# ── 10. status version info ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_status_includes_version_and_backend(rw_pipeline):
    pipeline, _ = rw_pipeline
    status = _get_tool(pipeline, "guardmcp_status")
    payload = await _call(status)
    assert payload["ok"] is True
    stats = payload["data"]["stats"]
    assert "server_version" in stats
    assert "protocol_version" in stats
    assert stats["backend"] == "mongodb"
    assert stats["backend_capability_count"] >= 1
