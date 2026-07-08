"""
Contract + integration regression: the tool layer's call sites must match the
REAL ``GuardPipeline`` method signatures.

Motivation — two shipped-green-but-broken blockers had the same root cause: a
tool call site passed a kwarg the real callee does not accept, hidden because
unit-test fake pipelines swallow generous ``**kwargs``.  The worst case was
``_run_with_confirm`` calling ``pipeline.execute_approved(eval_result,
database=database)`` while the real ``GuardPipeline.execute_approved(self,
eval_result)`` takes no ``database`` kwarg → TypeError on every confirmed
approval-required write.

Two layers of defense here:
  (a) A lightweight contract test using ``inspect.signature`` on the REAL
      methods, asserting every kwarg the tool layer passes is actually accepted
      (and that ``execute_approved`` still has NO ``database`` param).
  (c) An integration smoke that drives representative read + write(approval)
      tools through the REAL GuardPipeline wired to a mongomock client, so the
      confirm/approval path is exercised end-to-end against real signatures.
"""

from __future__ import annotations

import inspect
import json

import pytest
import pytest_asyncio
from mcp.server.fastmcp import FastMCP
from mongomock_motor import AsyncMongoMockClient

from guardmcp.core.approval.store import ApprovalStore
from guardmcp.core.audit.logger import AuditLogger
from guardmcp.core.models.domain import Action
from guardmcp.core.pipeline import GuardPipeline
from guardmcp.core.policy.engine import PolicyEngine
from guardmcp.core.policy.loader import PolicyLoader
from guardmcp.core.risk.engine import RiskEngine
from guardmcp.plugins.mongodb.executor import MongoExecutor
from guardmcp.server.tools import export as export_tools
from guardmcp.server.tools import read as read_tools
from guardmcp.server.tools import write as write_tools
from guardmcp.server.tools._common import ToolContext

# ─────────────────────────────────────────────────────────────────────────────
# (a) Signature contract — kwargs the tool layer passes must be accepted.
#
# Each entry documents a REAL call site (file:line) and the parameter names it
# supplies.  If a method signature drops one of these, or a call site grows a
# kwarg the method never had, the corresponding assertion fails in CI instead of
# hiding behind a **kwargs-swallowing fake pipeline.
# ─────────────────────────────────────────────────────────────────────────────

# method name -> set of parameter names the tool layer passes to it.
_CALL_SITE_KWARGS: dict[str, set[str]] = {
    # _common.py: evaluate(agent, collection, action, params, database=...)
    # meta/explain.py adds trace= and policy_override=; meta/plan.py the base set.
    "evaluate": {
        "agent",
        "collection",
        "action",
        "params",
        "database",
        "trace",
        "policy_override",
    },
    # read.py / meta/plan.py: run(agent, collection, action, params, database=...)
    "run": {"agent", "collection", "action", "params", "database"},
    # _common.py: _execute_and_build(req, policy, database=...)
    "_execute_and_build": {"req", "policy", "database"},
    # read.py: discover_collections(agent, database=...)
    "discover_collections": {"agent", "database"},
    # read.py: describe_collection(agent, collection, database=...)
    "describe_collection": {"agent", "collection", "database"},
    # meta/capabilities.py, meta/status.py: pipeline._get_executor() — no args.
    "_get_executor": set(),
    # meta/status.py, read.py: pipeline.active_connection() — no args.
    "active_connection": set(),
    # read.py: pipeline.list_connections() — no args.
    "list_connections": set(),
    # read.py: pipeline.switch_connection_audited(agent, connection_name)
    # — called positionally, but the PARAM NAMES still catch a rename/removal.
    "switch_connection_audited": {"agent", "name"},
}


@pytest.mark.parametrize("method_name,expected_kwargs", sorted(_CALL_SITE_KWARGS.items()))
def test_pipeline_method_accepts_tool_call_site_kwargs(method_name, expected_kwargs):
    """Every kwarg the tool layer passes must be a real parameter of the method."""
    method = getattr(GuardPipeline, method_name)
    params = inspect.signature(method).parameters
    accepts_var_kw = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())
    missing = {name for name in expected_kwargs if name not in params}
    # A method with **kwargs would accept anything — but none of these do, and
    # relying on **kwargs is exactly the trap we are guarding against.
    assert not accepts_var_kw, (
        f"GuardPipeline.{method_name} has **kwargs; tighten it so mismatched "
        f"tool kwargs fail loudly instead of being silently swallowed."
    )
    assert not missing, (
        f"GuardPipeline.{method_name} is missing parameters the tool layer passes: "
        f"{sorted(missing)}. Either the call site or the signature drifted."
    )


def test_execute_approved_takes_only_eval_result_no_database_kwarg():
    """
    Regression for the shipped TypeError: execute_approved must accept exactly
    one argument (eval_result) beyond self, and must NOT have a ``database``
    parameter.  _run_with_confirm calls ``pipeline.execute_approved(eval_result)``
    with no kwargs; reintroducing ``database=`` would raise TypeError at runtime.
    """
    params = inspect.signature(GuardPipeline.execute_approved).parameters
    non_self = [n for n in params if n != "self"]
    assert non_self == ["eval_result"], (
        f"execute_approved signature drifted: expected only (self, eval_result), "
        f"got {list(params)}"
    )
    assert "database" not in params, (
        "execute_approved must NOT accept a `database` kwarg — the tool layer "
        "does not pass one; the DB rides on eval_result.request.database."
    )


# ─────────────────────────────────────────────────────────────────────────────
# (c) Integration smoke — REAL GuardPipeline + mongomock, driven through tools.
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def rw_policy_file(tmp_path):
    """Read/write policy: find allowed, delete_one HIGH → approval required."""
    p = tmp_path / "policy.yaml"
    p.write_text("""
agent: claude
mode: readwrite
collections:
  allow:
    - orders
    - users
mask_fields:
  - email
approval:
  high: true
  critical: true
""")
    return p


class _MockMongoClient:
    """Mongomock-backed client exposing the executor's expected surface."""

    def __init__(self):
        self._client = AsyncMongoMockClient()

    def get_collection(self, name, database=None):
        return self._client["testdb"][name]

    def get_db(self, database=None):
        return self._client["testdb"]

    async def list_collection_names(self, database=None):
        return await self._client["testdb"].list_collection_names()

    async def list_databases(self):  # noqa: RUF029 - uniform async interface
        return [{"name": "testdb", "sizeOnDisk": 0}]

    def close(self):
        pass


@pytest_asyncio.fixture
async def real_pipeline(rw_policy_file, tmp_path):
    """A REAL GuardPipeline (no fakes) over a mongomock executor."""
    loader = PolicyLoader(rw_policy_file)
    loader.load()
    client = _MockMongoClient()
    # Seed a document so the approved delete has something to remove.
    await client.get_collection("orders").insert_one({"_id": 42, "status": "open"})
    return GuardPipeline(
        policy_loader=loader,
        policy_engine=PolicyEngine(),
        risk_engine=RiskEngine(),
        audit_logger=AuditLogger(tmp_path / "audit.jsonl"),
        approval_store=ApprovalStore(timeout_seconds=1.0),
        executor=MongoExecutor(client),
    )


def _make_mcp(pipeline, settings=None):
    """Register read + write + export tools against the REAL pipeline."""
    mcp = FastMCP("contract")
    ctx = ToolContext(
        get_pipeline=lambda: pipeline,
        get_agent=lambda: "claude",
        get_settings=lambda: settings,
    )
    read_tools.register(mcp, ctx)
    write_tools.register(mcp, ctx)
    export_tools.register(mcp, ctx)
    return mcp


class _ConfirmingContext:
    """Elicit stub that always accepts — drives the approval confirm branch."""

    async def elicit(self, *, message, schema):
        class _R:
            action = "accept"

            class data:
                confirmed = True

        return _R()


@pytest.mark.asyncio
async def test_read_find_smoke_through_real_pipeline(real_pipeline):
    """A read tool drives evaluate → run → execute end-to-end (no TypeError)."""
    mcp = _make_mcp(real_pipeline)
    # Read tools take no ctx first arg.
    raw = await mcp._tool_manager.get_tool("mongodb_find").fn(collection="orders")
    result = json.loads(raw)
    assert result.get("ok") is True, result
    ids = [doc.get("_id") for doc in result["data"]["documents"]]
    assert 42 in ids


@pytest.mark.asyncio
async def test_write_approval_path_smoke_through_real_pipeline(real_pipeline):
    """
    The full confirm/approval path against the REAL pipeline:
    evaluate → APPROVAL_REQUIRED → confirm → execute_approved(eval_result).

    This is the exact path the shipped `database=` kwarg broke.  With the real
    GuardPipeline.execute_approved (1-arg) wired in, a reintroduced kwarg raises
    TypeError here rather than passing behind a lenient fake.
    """
    mcp = _make_mcp(real_pipeline)
    # Write tools take ctx (FastMCP Context) as the first positional arg.
    raw = await mcp._tool_manager.get_tool("mongodb_delete_one").fn(
        _ConfirmingContext(),
        collection="orders",
        filter={"_id": 42},
    )
    result = json.loads(raw)
    assert result.get("ok") is True, result
    # The document seeded in the fixture was actually deleted.
    remaining = await real_pipeline.run("claude", "orders", Action.FIND, {"filter": {"_id": 42}})
    assert remaining["data"]["documents"] == []


@pytest.mark.asyncio
async def test_create_collection_ddl_smoke_through_real_pipeline(real_pipeline):
    """Newest DDL tool (this session) through the REAL pipeline — same
    regression class as the delete_one smoke above, for the newer call sites."""
    mcp = _make_mcp(real_pipeline)
    # "users" is policy-permitted (rw_policy_file) but not yet created —
    # unlike "orders", which the fixture already seeded via insert_one.
    raw = await mcp._tool_manager.get_tool("mongodb_create_collection").fn(
        _ConfirmingContext(), collection="users"
    )
    result = json.loads(raw)
    assert result.get("ok") is True, result


@pytest.mark.asyncio
async def test_export_smoke_through_real_pipeline(real_pipeline, tmp_path):
    """db_export (this session's newest tool) — reuses pipeline.run(), same
    contract as db_find, through the REAL pipeline end to end."""

    class _Settings:
        export_dir = tmp_path / "exports"
        export_ttl_seconds = 300.0

    mcp = _make_mcp(real_pipeline, settings=_Settings())
    raw = await mcp._tool_manager.get_tool("db_export").fn(collection="orders", mode="find")
    result = json.loads(raw)
    assert result.get("ok") is True, result
    assert result["data"]["document_count"] == 1
