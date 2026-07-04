"""Tests: per-call `database` parameter on write tools (Task 5)."""

import json

import pytest
from mcp.server.fastmcp import FastMCP

from guardmcp.core.models.domain import Action, Decision, DecisionStatus, Request, RiskLevel
from guardmcp.core.pipeline import EvalResult
from guardmcp.server.tools import write as write_tools
from guardmcp.server.tools._common import ToolContext


class _Pipeline:
    def __init__(self):
        self.eval_calls = []
        self._registry = None
        self._audit = _A()

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
            decision=Decision(status=DecisionStatus.DENIED, reason="x", code="POLICY_DENIED"),
            policy=None,
        )


class _A:
    def build(self, **k):
        return k

    async def log(self, r):
        return None


def _register():
    mcp = FastMCP("t")
    pipe = _Pipeline()
    box = {"db": "sessiondb"}
    ctx = ToolContext(
        get_pipeline=lambda: pipe,
        get_agent=lambda: "claude",
        get_settings=lambda: None,
        get_active_database=lambda: box["db"],
        set_active_database=lambda v: box.__setitem__("db", v),
    )
    write_tools.register(mcp, ctx)
    return mcp, pipe, box


class _FakeContext:
    """Minimal FastMCP Context stub for write tools that call _elicit_confirm."""

    async def elicit(self, *, message, schema):
        # Default: deny (safe; pipeline returns DENIED before elicit is reached in tests)
        class _R:
            action = "cancel"
            data = None

        return _R()


_FAKE_CTX = _FakeContext()


# ── Regression: approval-path pipeline with REAL 1-arg execute_approved ──────


class _ApprovalPipeline:
    """
    Fake pipeline that returns APPROVAL_REQUIRED so the confirm branch in
    _run_with_confirm is exercised.  execute_approved takes EXACTLY one positional
    arg (beyond self) — no database kwarg — mirroring the real GuardPipeline
    signature.  A reintroduced `database=` kwarg would raise TypeError here.
    """

    def __init__(self):
        self.approved_eval = None
        self.execute_approved_db = None  # captures req.database from inside
        self._registry = None
        self._audit = _A()

    def evaluate(self, agent, collection, action, params, database=None):
        return EvalResult(
            request=Request(
                agent=agent,
                collection=collection,
                action=action,
                params=params,
                database=database,
            ),
            decision=Decision(
                status=DecisionStatus.APPROVAL_REQUIRED,
                reason="high-risk delete",
                code="APPROVAL_REQUIRED",
                risk=RiskLevel.HIGH,
            ),
            policy=None,
        )

    async def execute_approved(self, eval_result):
        # Exactly 1 positional arg (no database kwarg) — matches real signature.
        self.approved_eval = eval_result
        self.execute_approved_db = eval_result.request.database
        return {"status": "success", "data": {"deleted": 1}, "neutral": {}}


class _ConfirmingContext:
    """Elicit stub that always accepts (confirmed=True)."""

    async def elicit(self, *, message, schema):
        class _R:
            action = "accept"

            class data:
                confirmed = True

        return _R()


_CONFIRMING_CTX = _ConfirmingContext()


async def _call(mcp, name, **kw):
    # Write tools take ctx: Context as first positional arg (FastMCP injection).
    return json.loads(await mcp._tool_manager.get_tool(name).fn(_FAKE_CTX, **kw))


@pytest.mark.asyncio
async def test_insert_threads_per_call_database():
    """Per-call database is passed through to pipeline.evaluate for insert_one."""
    mcp, pipe, _ = _register()
    await _call(mcp, "mongodb_insert_one", collection="user", document={"a": 1}, database="db1")
    assert ("user", "db1") in pipe.eval_calls


@pytest.mark.asyncio
async def test_insert_uses_active_database_when_omitted():
    """Omitting database falls back to session active db for insert_one."""
    mcp, pipe, _ = _register()
    await _call(mcp, "mongodb_insert_one", collection="user", document={"a": 1})
    assert ("user", "sessiondb") in pipe.eval_calls


@pytest.mark.asyncio
async def test_insert_many_threads_per_call_database():
    """Per-call database is passed through to pipeline.evaluate for insert_many."""
    mcp, pipe, _ = _register()
    await _call(mcp, "mongodb_insert_many", collection="logs", documents=[{"b": 2}], database="db2")
    assert ("logs", "db2") in pipe.eval_calls


@pytest.mark.asyncio
async def test_update_one_threads_per_call_database():
    """Per-call database is passed through to pipeline.evaluate for update_one."""
    mcp, pipe, _ = _register()
    await _call(
        mcp,
        "mongodb_update_one",
        collection="orders",
        filter={"_id": 1},
        update={"$set": {"status": "done"}},
        database="proddb",
    )
    assert ("orders", "proddb") in pipe.eval_calls


@pytest.mark.asyncio
async def test_update_many_threads_per_call_database():
    """Per-call database is passed through to pipeline.evaluate for update_many."""
    mcp, pipe, _ = _register()
    await _call(
        mcp,
        "mongodb_update_many",
        collection="events",
        filter={"active": True},
        update={"$set": {"active": False}},
        database="analyticsdb",
    )
    assert ("events", "analyticsdb") in pipe.eval_calls


@pytest.mark.asyncio
async def test_delete_one_threads_per_call_database():
    """Per-call database is passed through to pipeline.evaluate for delete_one."""
    mcp, pipe, _ = _register()
    await _call(
        mcp, "mongodb_delete_one", collection="sessions", filter={"_id": 99}, database="cachedb"
    )
    assert ("sessions", "cachedb") in pipe.eval_calls


@pytest.mark.asyncio
async def test_delete_many_threads_per_call_database():
    """Per-call database is passed through to pipeline.evaluate for delete_many."""
    mcp, pipe, _ = _register()
    await _call(
        mcp, "mongodb_delete_many", collection="logs", filter={"level": "debug"}, database="logdb"
    )
    assert ("logs", "logdb") in pipe.eval_calls


@pytest.mark.asyncio
async def test_approval_path_does_not_pass_database_kwarg_to_execute_approved():
    """
    Regression: _run_with_confirm must call execute_approved(eval_result) with NO
    database= kwarg.  The real GuardPipeline.execute_approved(self, eval_result)
    accepts only one positional arg; the old call site passed `database=database`
    which raises TypeError.  This test uses a pipeline whose execute_approved has
    exactly that 1-arg signature — a reintroduced kwarg will fail here.

    Also verifies that the database is NOT lost: eval_result.request.database
    carries it through to the confirmed execution.
    """
    mcp = FastMCP("t")
    pipe = _ApprovalPipeline()
    box = {"db": "approvaldb"}
    ctx = ToolContext(
        get_pipeline=lambda: pipe,
        get_agent=lambda: "claude",
        get_settings=lambda: None,
        get_active_database=lambda: box["db"],
        set_active_database=lambda v: box.__setitem__("db", v),
    )
    write_tools.register(mcp, ctx)

    # Call delete_one which goes through _run_with_confirm; pipeline returns
    # APPROVAL_REQUIRED; _ConfirmingContext accepts; execute_approved is called.
    result = json.loads(
        await mcp._tool_manager.get_tool("mongodb_delete_one").fn(
            _CONFIRMING_CTX,
            collection="orders",
            filter={"_id": 42},
            database="approvaldb",
        )
    )

    # Must not raise TypeError — the approved eval must have been stored.
    assert pipe.approved_eval is not None, "execute_approved was never called"
    # Database is preserved on the request carried through eval_result.
    assert pipe.execute_approved_db == "approvaldb"
    # Tool must return success (the response envelope uses ok=True).
    assert result.get("ok") is True
