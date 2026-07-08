"""
Integration tests — multi-database Phase 3 tool-exposure.

Exercises the registered MCP tools (read + write + use_database +
list_databases + status + switch_connection) through fake pipelines,
asserting end-to-end database-axis behaviour across all registered tools.

Harness mirrors the per-task unit tests (Tasks 3–6):
  - mcp._tool_manager.get_tool(name).fn(**kw) invocation
  - {"ok": ...} envelope assertions
  - ToolContext wired to a mutable box dict for active-db tracking
"""

from __future__ import annotations

import json

import pytest
from mcp.server.fastmcp import FastMCP

from guardmcp.core.interfaces.errors import ErrorCode
from guardmcp.core.models.domain import Action, Decision, DecisionStatus, Request
from guardmcp.core.pipeline import EvalResult
from guardmcp.core.policy.models import CollectionPolicy, DatabaseScope, Policy
from guardmcp.server.tools import read as read_tools
from guardmcp.server.tools import write as write_tools
from guardmcp.server.tools._common import ToolContext

# ── Shared fakes ─────────────────────────────────────────────────────────────


class _ReadPipeline:
    """Fake pipeline for read-tool tests."""

    def __init__(self, policy: Policy | None = None):
        self.run_calls: list[tuple] = []
        self._registry = None
        self._policies = _PolicyStore(policy or Policy(agent="claude"))

    async def run(self, agent, collection, action, params, database=None):
        self.run_calls.append(
            (collection, action.value if hasattr(action, "value") else action, database)
        )
        return {"status": "success", "data": {"count": 0}}

    async def discover_collections(self, agent, database=None):
        self.run_calls.append(("<list>", "list", database))
        return []

    async def describe_collection(self, agent, collection, database=None):
        self.run_calls.append((collection, "describe", database))
        return {"collection": collection, "fields": {}}

    async def use_database_audited(self, agent, name):
        return self._policies.get(agent).database_permitted(name)

    def active_connection(self):
        return "default"

    def list_connections(self):
        return ["default"]

    async def switch_connection_audited(self, agent, name):
        return name in self.list_connections()

    def supports(self, capability) -> bool:
        return True


class _PolicyStore:
    def __init__(self, policy: Policy) -> None:
        self._p = policy

    def get(self, agent: str) -> Policy:
        return self._p


class _WritePipeline:
    """Fake pipeline for write-tool tests (DENIED path is default safe path)."""

    def __init__(self, decision_status: DecisionStatus = DecisionStatus.DENIED):
        self.eval_calls: list[tuple] = []
        self.exec_calls: list[tuple] = []
        self._registry = None
        self._audit = _FakeAudit()
        self._decision_status = decision_status

    def evaluate(self, agent, collection, action, params, database=None):
        self.eval_calls.append((collection, database))
        return EvalResult(
            request=Request(
                agent=agent,
                collection=collection,
                action=Action.INSERT_ONE,
                params=params,
                database=database,
            ),
            decision=Decision(
                status=self._decision_status,
                reason="x",
                code="POLICY_DENIED",
            ),
            policy=None,
        )

    async def execute_approved(self, eval_result):
        # Real signature: no database kwarg — database is on eval_result.request.database.
        self.exec_calls.append((eval_result.request.collection, eval_result.request.database))
        return {"status": "success", "data": {"inserted_id": "abc"}}


class _FakeAudit:
    def build(self, **k):
        return k

    async def log(self, r):
        return None


class _FakeContext:
    """Minimal FastMCP Context stub for write tools that call _elicit_confirm."""

    async def elicit(self, *, message, schema):
        class _R:
            action = "cancel"
            data = None

        return _R()


_FAKE_CTX = _FakeContext()


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_box(initial: str | None = None) -> dict:
    return {"db": initial}


def _read_ctx(pipe, box: dict, policy: Policy | None = None) -> tuple[FastMCP, _ReadPipeline]:
    mcp = FastMCP("t")
    if policy and not isinstance(pipe._policies._p, type(None)):
        pipe._policies = _PolicyStore(policy)
    ctx = ToolContext(
        get_pipeline=lambda: pipe,
        get_agent=lambda: "claude",
        get_settings=lambda: None,
        get_active_database=lambda: box["db"],
        set_active_database=lambda v: box.__setitem__("db", v),
    )
    read_tools.register(mcp, ctx)
    return mcp


def _write_ctx(pipe, box: dict) -> FastMCP:
    mcp = FastMCP("t")
    ctx = ToolContext(
        get_pipeline=lambda: pipe,
        get_agent=lambda: "claude",
        get_settings=lambda: None,
        get_active_database=lambda: box["db"],
        set_active_database=lambda v: box.__setitem__("db", v),
    )
    write_tools.register(mcp, ctx)
    return mcp


async def _call_read(mcp: FastMCP, name: str, **kw):
    return json.loads(await mcp._tool_manager.get_tool(name).fn(**kw))


async def _call_write(mcp: FastMCP, name: str, **kw):
    # Write tools take ctx: Context as first positional arg (FastMCP injection).
    return json.loads(await mcp._tool_manager.get_tool(name).fn(_FAKE_CTX, **kw))


# ═════════════════════════════════════════════════════════════════════════════
# Requirement 1: per-call database reaches the pipeline for READ and WRITE tools
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_req1_per_call_database_read_tool():
    """A per-call `database` arg reaches pipeline.run for a read tool (count)."""
    pipe = _ReadPipeline()
    box = _make_box()
    mcp = _read_ctx(pipe, box)

    await _call_read(mcp, "mongodb_count", collection="user", filter={}, database="targetdb")

    # Assert the database was threaded through — non-vacuous assertion on real value
    assert any(
        c[0] == "user" and c[2] == "targetdb" for c in pipe.run_calls
    ), f"Expected ('user', *, 'targetdb') in run_calls, got {pipe.run_calls}"


@pytest.mark.asyncio
async def test_req1_per_call_database_write_tool():
    """A per-call `database` arg reaches pipeline.evaluate for a write tool (insert_one)."""
    pipe = _WritePipeline()
    box = _make_box()
    mcp = _write_ctx(pipe, box)

    await _call_write(
        mcp, "mongodb_insert_one", collection="orders", document={"x": 1}, database="writedb"
    )

    assert ("orders", "writedb") in pipe.eval_calls, (
        f"Expected ('orders', 'writedb') in eval_calls, got {pipe.eval_calls}"
    )


# ═════════════════════════════════════════════════════════════════════════════
# Requirement 2: use_database sets active db; subsequent no-db call uses it;
#                per-call database on the NEXT call overrides it
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_req2_use_database_sets_active_and_subsequent_read_uses_it():
    """
    use_database("db1") → active db = "db1"
    → subsequent count with no database arg uses "db1"
    """
    policy = Policy(
        agent="claude",
        databases_allow=["db1"],
        databases={"db1": DatabaseScope(collections=CollectionPolicy(allow=["*"]))},
    )
    pipe = _ReadPipeline(policy)
    box = _make_box()
    mcp = _read_ctx(pipe, box)

    # Step 1: set active db
    out = await _call_read(mcp, "mongodb_use_database", database="db1")
    assert out["ok"] is True, f"use_database failed: {out}"
    assert box["db"] == "db1"

    # Step 2: subsequent count with NO database arg → resolves to "db1"
    pipe.run_calls.clear()
    await _call_read(mcp, "mongodb_count", collection="user", filter={})
    assert any(c[0] == "user" and c[2] == "db1" for c in pipe.run_calls), (
        f"Expected active db 'db1' threaded through, got {pipe.run_calls}"
    )


@pytest.mark.asyncio
async def test_req2_per_call_database_overrides_active():
    """
    After use_database("db1"), a per-call database="db2" on the next call OVERRIDES it.
    Resolution order: per-call → active → None.
    """
    policy = Policy(
        agent="claude",
        databases_allow=["db1"],
        databases={"db1": DatabaseScope(collections=CollectionPolicy(allow=["*"]))},
    )
    pipe = _ReadPipeline(policy)
    box = _make_box()
    mcp = _read_ctx(pipe, box)

    # Set active to db1
    await _call_read(mcp, "mongodb_use_database", database="db1")
    assert box["db"] == "db1"

    # Override with per-call db2 — must beat the active db
    pipe.run_calls.clear()
    await _call_read(mcp, "mongodb_count", collection="user", filter={}, database="db2")
    assert any(c[0] == "user" and c[2] == "db2" for c in pipe.run_calls), (
        f"Per-call 'db2' should override active 'db1', got {pipe.run_calls}"
    )
    # Active db is NOT changed by per-call override
    assert box["db"] == "db1", "Per-call database must not mutate the active db"


# ═════════════════════════════════════════════════════════════════════════════
# Requirement 3: use_database on an unlisted db → DATABASE_NOT_ALLOWED,
#                active db unchanged
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_req3_use_database_not_allowed_leaves_active_unchanged():
    """use_database on a db not in databases_allow → DATABASE_NOT_ALLOWED, active unchanged."""
    policy = Policy(
        agent="claude",
        databases_allow=["db1"],
        databases={"db1": DatabaseScope(collections=CollectionPolicy(allow=["*"]))},
    )
    pipe = _ReadPipeline(policy)
    box = _make_box("db1")  # active db starts as db1
    mcp = _read_ctx(pipe, box)

    out = await _call_read(mcp, "mongodb_use_database", database="secret_db")

    assert out["ok"] is False, f"Expected denied, got {out}"
    error_code = out.get("error", {}).get("code")
    assert error_code == ErrorCode.DATABASE_NOT_ALLOWED.value, (
        f"Expected DATABASE_NOT_ALLOWED code, got {error_code!r}; full response: {out}"
    )
    # Active db must be unchanged
    assert box["db"] == "db1", f"Active db changed unexpectedly to {box['db']}"


# ═════════════════════════════════════════════════════════════════════════════
# Requirement 4: active db is PER-CONNECTION (core/registry/connections.py:
# ConnectionEntry.active_database), not a single server-level slot. Switching to
# a connection restores THAT connection's own remembered active db instead of
# unconditionally clearing it — see tests/unit/test_connections.py for the
# cross-connection isolation coverage (registry-level, two distinct entries).
# This harness only has one fake connection ("default"), so it covers the
# self-switch case: switching to the connection you're already on must NOT lose
# its remembered db (the old single-slot design cleared it unconditionally).
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_req4_switch_connection_preserves_that_connections_active_db():
    """
    After use_database("db1"), switching to the SAME connection ("default")
    must NOT lose its remembered active db (per-connection memory, not a
    single shared slot cleared by every switch).
    """
    policy = Policy(
        agent="claude",
        databases_allow=["db1"],
        databases={"db1": DatabaseScope(collections=CollectionPolicy(allow=["*"]))},
    )
    pipe = _ReadPipeline(policy)
    box = _make_box()
    mcp = _read_ctx(pipe, box)

    # Set active db
    await _call_read(mcp, "mongodb_use_database", database="db1")
    assert box["db"] == "db1"

    # Switch to the connection we're already on → its own remembered db stays.
    out = await _call_read(mcp, "mongodb_switch_connection", connection_name="default")
    assert out["ok"] is True, f"switch_connection failed: {out}"
    assert box["db"] == "db1", f"Expected db1 preserved after self-switch, got {box['db']}"

    # Subsequent no-db count still resolves to the remembered db1.
    pipe.run_calls.clear()
    await _call_read(mcp, "mongodb_count", collection="user", filter={})
    assert any(c[0] == "user" and c[2] == "db1" for c in pipe.run_calls), (
        f"Expected db1 threaded through, got {pipe.run_calls}"
    )


# ═════════════════════════════════════════════════════════════════════════════
# Requirement 5: list_databases excludes a db not in databases_allow
# ═════════════════════════════════════════════════════════════════════════════


class _ListDbPipeline(_ReadPipeline):
    """Extends _ReadPipeline with a run() that returns a list of databases."""

    def __init__(self, policy: Policy, dbs: list[str]) -> None:
        super().__init__(policy)
        self._dbs = dbs

    async def run(self, agent, collection, action, params, database=None):
        self.run_calls.append((collection, action, database))
        return {
            "status": "success",
            "data": {"databases": [{"name": n} for n in self._dbs]},
        }


@pytest.mark.asyncio
async def test_req5_list_databases_excludes_disallowed():
    """list_databases returns only databases in databases_allow; unlisted ones filtered out."""
    policy = Policy(agent="claude", databases_allow=["db1", "db2"])
    pipe = _ListDbPipeline(policy, ["db1", "db2", "secret_db"])
    box = _make_box()
    mcp = _read_ctx(pipe, box)

    out = await _call_read(mcp, "mongodb_list_databases")

    assert out["ok"] is True, f"list_databases failed: {out}"
    names = {d["name"] for d in out["data"]["databases"]}
    assert "db1" in names, "db1 should be in list"
    assert "db2" in names, "db2 should be in list"
    assert "secret_db" not in names, "secret_db should be excluded (not in databases_allow)"


# ═════════════════════════════════════════════════════════════════════════════
# Requirement 6 (Task-5 gap): WRITE APPROVAL_REQUIRED path threads database
# ═════════════════════════════════════════════════════════════════════════════


class _ApprovalPipeline(_WritePipeline):
    """
    Pipeline whose evaluate() returns APPROVAL_REQUIRED.
    A confirming FakeContext allows execute_approved to be called.
    """

    def __init__(self):
        super().__init__(decision_status=DecisionStatus.APPROVAL_REQUIRED)

    def evaluate(self, agent, collection, action, params, database=None):
        self.eval_calls.append((collection, database))
        return EvalResult(
            request=Request(
                agent=agent,
                collection=collection,
                action=Action.INSERT_ONE,
                params=params,
                database=database,
            ),
            decision=Decision(
                status=DecisionStatus.APPROVAL_REQUIRED,
                reason="high risk",
                code="APPROVAL_REQUIRED",
            ),
            policy=None,
        )

    async def execute_approved(self, eval_result):
        # Real signature: no database kwarg — database is on eval_result.request.database.
        self.exec_calls.append((eval_result.request.collection, eval_result.request.database))
        return {"status": "success", "data": {"inserted_id": "xyz"}}


class _ConfirmingContext:
    """FastMCP Context stub that confirms approval (action='accept', confirmed=True)."""

    async def elicit(self, *, message, schema):
        class _R:
            action = "accept"

            class data:
                confirmed = True

        return _R()


@pytest.mark.asyncio
async def test_req6_approval_required_path_evaluate_receives_database():
    """
    Write tool with APPROVAL_REQUIRED: pipeline.evaluate receives the resolved database.
    The _FakeContext (default cancel) still calls evaluate before elicit, so eval_calls
    is populated even when user cancels.
    """
    pipe = _ApprovalPipeline()
    box = _make_box()
    mcp = FastMCP("t2")
    ctx = ToolContext(
        get_pipeline=lambda: pipe,
        get_agent=lambda: "claude",
        get_settings=lambda: None,
        get_active_database=lambda: box["db"],
        set_active_database=lambda v: box.__setitem__("db", v),
    )
    write_tools.register(mcp, ctx)

    # Use the cancel context — evaluate is called before elicit, so eval_calls is populated
    await mcp._tool_manager.get_tool("mongodb_insert_one").fn(
        _FAKE_CTX, collection="logs", document={"msg": "hi"}, database="approvaldb"
    )

    # evaluate must have received the database
    assert ("logs", "approvaldb") in pipe.eval_calls, (
        f"pipeline.evaluate must receive database='approvaldb', got eval_calls={pipe.eval_calls}"
    )


@pytest.mark.asyncio
async def test_req6_approval_required_execute_approved_receives_database():
    """
    When user confirms approval, execute_approved also receives the resolved database.
    """
    pipe = _ApprovalPipeline()
    mcp = FastMCP("t3")
    box = _make_box()
    ctx = ToolContext(
        get_pipeline=lambda: pipe,
        get_agent=lambda: "claude",
        get_settings=lambda: None,
        get_active_database=lambda: box["db"],
        set_active_database=lambda v: box.__setitem__("db", v),
    )
    write_tools.register(mcp, ctx)

    confirming_ctx = _ConfirmingContext()
    out_str = await mcp._tool_manager.get_tool("mongodb_insert_one").fn(
        confirming_ctx, collection="events", document={"t": 1}, database="execdb"
    )
    out = json.loads(out_str)

    assert ("events", "execdb") in pipe.eval_calls, (
        f"evaluate must receive database='execdb', got {pipe.eval_calls}"
    )
    assert ("events", "execdb") in pipe.exec_calls, (
        f"execute_approved must receive database='execdb', got {pipe.exec_calls}"
    )
    # Verify the call succeeded (not vacuously passing due to earlier denial)
    assert out["ok"] is True, f"Expected approved insert to succeed, got {out}"


# ═════════════════════════════════════════════════════════════════════════════
# Requirement 7: back-compat — no databases_allow + no per-call database
#                → pipeline receives None (connection default)
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_req7_backcompat_read_resolves_none_when_no_db_context():
    """
    With no databases_allow and no per-call database, read tool resolves to None.
    Back-compat: single-database mode behaves identically to pre-multi-db.
    """
    pipe = _ReadPipeline()  # policy has no databases_allow
    box = _make_box()  # active db = None
    mcp = _read_ctx(pipe, box)

    await _call_read(mcp, "mongodb_count", collection="user", filter={})

    assert any(c[0] == "user" and c[2] is None for c in pipe.run_calls), (
        f"Back-compat: database should be None when no context is set, got {pipe.run_calls}"
    )


@pytest.mark.asyncio
async def test_req7_backcompat_write_resolves_none_when_no_db_context():
    """
    With no databases_allow and no per-call database, write tool resolves to None.
    Back-compat: single-database mode for writes.
    """
    pipe = _WritePipeline()
    box = _make_box()  # active db = None
    mcp = _write_ctx(pipe, box)

    await _call_write(
        mcp, "mongodb_insert_one", collection="user", document={"a": 1}
        # No database kwarg
    )

    assert ("user", None) in pipe.eval_calls, (
        f"Back-compat: evaluate must receive None when no db context, got {pipe.eval_calls}"
    )


@pytest.mark.asyncio
async def test_req7_backcompat_find_resolves_none():
    """Back-compat for find (most common read op): no database arg → None."""
    pipe = _ReadPipeline()
    box = _make_box()
    mcp = _read_ctx(pipe, box)

    await _call_read(mcp, "mongodb_find", collection="orders", filter={})

    assert any(c[0] == "orders" and c[2] is None for c in pipe.run_calls), (
        f"Back-compat: find must pass None when no database context, got {pipe.run_calls}"
    )
