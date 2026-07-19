# Multi-Database Governance — Phase 3 (MCP Tool Exposure) Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the governed `database` axis to MCP clients — per-call `database` on all data/introspection/write tools, a `use_database` active-session tool, policy-filtered `list_databases`, and active/allowed-database in `guardmcp_status` — so agents can run multi-database (multi-hop) workflows. Omitting `database` with no `databases_allow` → byte-identical to today.

**Architecture:** A server-level active-database holder on `AppContext`, exposed via `ToolContext` accessors + a `_resolve_database(ctx, per_call)` helper (per-call → active → None→connection-default). Discovery methods (`discover_collections`/`describe_collection`) gain `database` (Phase 2 only did the run path). Tools thread the resolved database into `pipeline.run(..., database=)` / `_run_with_confirm(..., database=)` (both already database-aware from Phase 2).

**Tech Stack:** Python 3.12+, Pydantic v2, FastMCP, pytest/pytest-asyncio, motor.

## Global Constraints

- Backward compatible: omit `database` + no `databases_allow` → effective database is the connection default; every tool behaves byte-identically to today. All new params optional + trailing; `use_database`/status additions are additive.
- Both per-call `database` and `use_database` are gated by the Phase-1 database gate (`DATABASE_NOT_ALLOWED`) and audited.
- Resolution order: per-call `database` → active session db → connection default (None).
- `use_database` resets to connection default on `switch_connection`.
- Do NOT change masking/routing internals (Phases 1–2 done). Do NOT add cross-database relationship logic (next slice). Do NOT add `field_stats` (field-semantics branch).
- Run tests: `/Users/suresh/guardmcp/.venv/bin/python -m pytest <path> -v`. FULL regression each task: `/Users/suresh/guardmcp/.venv/bin/python -m pytest -q --deselect tests/integration/test_transport_lifecycle.py::test_streamable_http_db_tool_survives_session_boundary`. Eval: `/Users/suresh/guardmcp/.venv/bin/python -m guardmcp.eval evals/cases/` (42/42). Lint: `/Users/suresh/guardmcp/.venv/bin/python -m ruff check src tests`. (No `python` on PATH.) **After each task run `git status` to confirm no uncommitted edit is masking a committed-code failure.**
- Codebase-orientation rule (repo mandate): before reading a source file to understand it, run `graphify query "<question>"`; if graphify is unavailable in the shell, read the file directly. Applies to subagents.
- Commit bodies end with: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

---

### Task 1: Active-database holder + resolution helper (`ToolContext`, `AppContext`, `_common`)

**Files:**
- Modify: `src/guardmcp/server/tools/_common.py` (`ToolContext` + `_resolve_database`)
- Modify: `src/guardmcp/__main__.py` (`AppContext` active-db field + wire ToolContext accessors)
- Test: `tests/unit/test_active_database_holder.py`

**Interfaces:**
- Produces:
  - `AppContext.active_database: str | None = None` (mutable).
  - `ToolContext.get_active_database: Callable[[], str | None]` and `ToolContext.set_active_database: Callable[[str | None], None]` (new dataclass fields).
  - `_resolve_database(ctx: ToolContext, per_call: str | None) -> str | None` in `_common.py` → `per_call or ctx.get_active_database()`.

**Orientation:** run `graphify query "ToolContext dataclass AppContext build register_tools"`; else read `_common.py` (`ToolContext`) and `__main__.py` (`AppContext`, `build`, where `ToolContext(...)` is constructed and `register_tools` is called).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_active_database_holder.py
from guardmcp.server.tools._common import ToolContext, _resolve_database


def _ctx(active=None):
    box = {"db": active}
    return ToolContext(
        get_pipeline=lambda: None, get_agent=lambda: "claude", get_settings=lambda: None,
        get_active_database=lambda: box["db"],
        set_active_database=lambda v: box.__setitem__("db", v),
    )


def test_resolve_prefers_per_call():
    ctx = _ctx(active="sessiondb")
    assert _resolve_database(ctx, "calldb") == "calldb"


def test_resolve_falls_back_to_active():
    ctx = _ctx(active="sessiondb")
    assert _resolve_database(ctx, None) == "sessiondb"


def test_resolve_none_when_no_active():
    ctx = _ctx(active=None)
    assert _resolve_database(ctx, None) is None


def test_set_active_database_roundtrips():
    ctx = _ctx()
    ctx.set_active_database("db2")
    assert ctx.get_active_database() == "db2"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest tests/unit/test_active_database_holder.py -v`
Expected: FAIL — `ToolContext.__init__` missing `get_active_database`/`set_active_database`, or `_resolve_database` undefined.

- [ ] **Step 3: Write minimal implementation**

In `_common.py`, add two fields to the `ToolContext` dataclass (after `get_settings`):

```python
    get_active_database: Callable[[], str | None] = lambda: None
    set_active_database: Callable[[str | None], None] = lambda _v: None
```

(These defaults keep any existing `ToolContext(...)` construction valid; `build()` overrides them.) Add the helper:

```python
def _resolve_database(ctx: "ToolContext", per_call: str | None) -> str | None:
    """Effective database: per-call arg → active session db → None (connection default)."""
    return per_call or ctx.get_active_database()
```

Add `_resolve_database` to `__all__`.

In `__main__.py`: add `active_database: str | None = None` to the `AppContext` dataclass, and where `ToolContext(...)` is constructed for `register_tools`, wire the accessors to the AppContext instance, e.g.:

```python
    tool_ctx = ToolContext(
        get_pipeline=..., get_agent=..., get_settings=...,
        get_active_database=lambda: ctx.active_database,
        set_active_database=lambda v: setattr(ctx, "active_database", v),
    )
```

(Read the real construction site and match it; only add the two accessors.)

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest tests/unit/test_active_database_holder.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/guardmcp/server/tools/_common.py src/guardmcp/__main__.py tests/unit/test_active_database_holder.py
git commit -m "feat(tools): active-database holder + _resolve_database helper"
```

---

### Task 2: Thread `database` into discovery methods (`discover_collections`, `describe_collection`)

**Files:**
- Modify: `src/guardmcp/core/pipeline.py` (`discover_collections`, `describe_collection`)
- Test: `tests/unit/test_discovery_database.py`

**Interfaces:**
- Produces:
  - `discover_collections(self, agent, database: str | None = None) -> list[str]` — passes `database` to `executor.list_collections(database)`; audit records the database.
  - `describe_collection(self, agent, collection, database: str | None = None) -> dict | None` — passes `database` to `executor.collection_schema(..., database=database)`; uses `policy.mask_fields_for(collection, database)`.

**Orientation:** run `graphify query "GuardPipeline discover_collections describe_collection executor list_collections collection_schema"`; else read `core/pipeline.py` those two methods. Executor already accepts `database` (Phase 2).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_discovery_database.py
import pytest

from guardmcp.core.pipeline import GuardPipeline
from guardmcp.core.policy.engine import PolicyEngine
from guardmcp.core.policy.models import CollectionPolicy, DatabaseScope, Policy
from guardmcp.core.risk.engine import RiskEngine


class _Loader:
    def __init__(self, p): self._p = p
    def get(self, agent): return self._p


class _Executor:
    def __init__(self): self.calls = []
    async def list_collections(self, database=None):
        self.calls.append(("list", database)); return ["user"]
    async def collection_schema(self, collection, mask_fields, sample_size=None, database=None):
        self.calls.append(("schema", collection, database)); return {"_id": "objectId"}


class _Audit:
    def build(self, **k): return k
    async def log(self, r): return None


def _pipeline(p, ex):
    return GuardPipeline(policy_loader=_Loader(p), policy_engine=PolicyEngine(),
                         risk_engine=RiskEngine(), audit_logger=_Audit(),
                         approval_store=None, executor=ex)


@pytest.mark.asyncio
async def test_discover_collections_threads_database():
    p = Policy(agent="claude", databases_allow=["db1"],
               databases={"db1": DatabaseScope(collections=CollectionPolicy(allow=["user"]))})
    ex = _Executor()
    cols = await _pipeline(p, ex).discover_collections("claude", database="db1")
    assert cols == ["user"] and ("list", "db1") in ex.calls


@pytest.mark.asyncio
async def test_describe_collection_threads_database():
    p = Policy(agent="claude", databases_allow=["db1"],
               databases={"db1": DatabaseScope(collections=CollectionPolicy(allow=["user"]))})
    ex = _Executor()
    out = await _pipeline(p, ex).describe_collection("claude", "user", database="db1")
    assert out is not None and any(c == ("schema", "user", "db1") for c in ex.calls)


@pytest.mark.asyncio
async def test_discovery_backcompat_no_database():
    p = Policy(agent="claude", collections=CollectionPolicy(allow=["user"]))
    ex = _Executor()
    await _pipeline(p, ex).discover_collections("claude")
    assert ("list", None) in ex.calls
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest tests/unit/test_discovery_database.py -v`
Expected: FAIL — `discover_collections()`/`describe_collection()` have no `database` parameter.

- [ ] **Step 3: Write minimal implementation**

In `core/pipeline.py`:
- `discover_collections(self, agent, database: str | None = None)`: pass `database` to `executor.list_collections(database)`; permission-filter using `policy.scope_for(database).collections` (per-database allow/deny) if a database is given, else the flat collections as today; thread `database` into its `_audit_event(...)` call.
- `describe_collection(self, agent, collection, database: str | None = None)`: gate the collection via `policy.scope_for(database)`; call `executor.collection_schema(collection, policy.mask_fields_for(collection, database), database=database)`; thread `database` into `_audit_event`.

Keep `database=None` reproducing today's behavior exactly (flat scope, `executor.list_collections(None)` == configured DB).

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest tests/unit/test_discovery_database.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/guardmcp/core/pipeline.py tests/unit/test_discovery_database.py
git commit -m "feat(pipeline): thread database into discover_collections + describe_collection"
```

---

### Task 3: `use_database` tool + reset on `switch_connection`

**Files:**
- Modify: `src/guardmcp/core/pipeline.py` (add `use_database_audited`)
- Modify: `src/guardmcp/server/tools/read.py` (register `use_database`; reset active-db in the switch handler)
- Test: `tests/unit/test_use_database_tool.py`

**Interfaces:**
- Consumes: `Policy.database_permitted` (Phase 1); `ToolContext.set_active_database`/`get_active_database` (Task 1); existing `_switch_connection` handler.
- Produces:
  - `GuardPipeline.use_database_audited(self, agent, name: str) -> bool` — returns `policy.database_permitted(name)` for the agent's policy (True if permitted), audits the attempt (action `"use_database"`, the database recorded), mirroring `switch_connection_audited`.
  - New dual tool `db_use_database` / `mongodb_use_database(database: str)` — calls `use_database_audited`; on True sets `ctx.set_active_database(database)` + returns `ok({"active_database": database})`; on False returns `err(ErrorCode.DATABASE_NOT_ALLOWED, ...)`.
  - The existing `_switch_connection` handler calls `ctx.set_active_database(None)` after a successful switch.

**Orientation:** run `graphify query "switch_connection_audited _switch_connection register_dual audit_event"`; else read `pipeline.py` `switch_connection_audited` (mirror it) and `read.py` `_switch_connection`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_use_database_tool.py
import json

import pytest
from mcp.server.fastmcp import FastMCP

from guardmcp.core.policy.models import CollectionPolicy, DatabaseScope, Policy
from guardmcp.server.tools._common import ToolContext
from guardmcp.server.tools import read as read_tools


class _Pipeline:
    def __init__(self, policy): self._p = policy
    _registry = None
    async def use_database_audited(self, agent, name):
        return self._p.database_permitted(name)


def _register(policy):
    mcp = FastMCP("t")
    box = {"db": None}
    ctx = ToolContext(get_pipeline=lambda: _Pipeline(policy), get_agent=lambda: "claude",
                      get_settings=lambda: None,
                      get_active_database=lambda: box["db"],
                      set_active_database=lambda v: box.__setitem__("db", v))
    read_tools.register(mcp, ctx)
    return mcp, box


async def _call(mcp, name, **kw):
    tool = mcp._tool_manager.get_tool(name)
    return json.loads(await tool.fn(**kw))


@pytest.mark.asyncio
async def test_use_database_allowed_sets_active():
    p = Policy(agent="claude", databases_allow=["db1"],
               databases={"db1": DatabaseScope(collections=CollectionPolicy(allow=["user"]))})
    mcp, box = _register(p)
    out = await _call(mcp, "mongodb_use_database", database="db1")
    assert out["ok"] is True and box["db"] == "db1"


@pytest.mark.asyncio
async def test_use_database_denied():
    p = Policy(agent="claude", databases_allow=["db1"],
               databases={"db1": DatabaseScope(collections=CollectionPolicy(allow=["user"]))})
    mcp, box = _register(p)
    out = await _call(mcp, "mongodb_use_database", database="db2")
    assert out["ok"] is False and box["db"] is None
```

> Confirm the FastMCP invocation pattern against `tests/unit/test_mcp_tooling.py` / `test_plan_query_tool.py` (`_tool_manager.get_tool(name)` + `await tool.fn(**kw)`, envelope `{"ok": ...}`) and mirror it. Adapt if the repo differs.

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest tests/unit/test_use_database_tool.py -v`
Expected: FAIL — no `mongodb_use_database` tool registered.

- [ ] **Step 3: Write minimal implementation**

Add to `pipeline.py` (mirror `switch_connection_audited`):

```python
    async def use_database_audited(self, agent: str, name: str) -> bool:
        policy = self._policies.get(agent)
        permitted = policy is not None and policy.database_permitted(name)
        await self._audit_event(
            agent=agent, collection="*", action="use_database",
            status="allowed" if permitted else "denied",
            reason=None if permitted else f"database '{name}' not permitted by policy",
            database=name,
        )
        return permitted
```

In `read.py` `register(...)`, add a dual tool (mirror `db_switch_connection`):

```python
    _USE_DB_DESC = (
        "Set the active database for subsequent calls that omit a `database` arg.\n"
        "Use when: running several operations against one database.\n"
        "Do NOT use when: a single call — pass `database=` on that call instead.\n"
        "Side effects: changes which database later calls target (until changed or "
        "switch_connection resets it).\n"
        "Example: db_use_database(database='corestack_identity')"
    )

    @_validation_guard
    async def _use_database(database: str) -> str:
        ok_ = await get_pipeline().use_database_audited(get_agent(), database)
        if not ok_:
            return err(ErrorCode.DATABASE_NOT_ALLOWED,
                       f"database '{database}' is not permitted by policy.", retryable=False)
        ctx.set_active_database(database)
        return ok({"active_database": database})

    register_dual(mcp, "db_use_database", "mongodb_use_database",
                  _USE_DB_DESC, _annot(readOnlyHint=False, destructiveHint=False), _use_database)
```

In the existing `_switch_connection` handler, after a successful switch add `ctx.set_active_database(None)` (reset active db to the new connection's default). Import `DATABASE_NOT_ALLOWED` via the existing `ErrorCode` import.

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest tests/unit/test_use_database_tool.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/guardmcp/core/pipeline.py src/guardmcp/server/tools/read.py tests/unit/test_use_database_tool.py
git commit -m "feat(tools): use_database active-session tool + reset on switch_connection"
```

---

### Task 4: Per-call `database` on read/introspection tools

**Files:**
- Modify: `src/guardmcp/server/tools/read.py` (find, count, aggregate, schema, indexes, explain, list_collections)
- Modify: `src/guardmcp/server/tools/meta/explain.py` if `explain` lives there (check)
- Test: `tests/unit/test_read_tools_database.py`

**Interfaces:**
- Consumes: `_resolve_database(ctx, per_call)` (Task 1); `pipeline.run(..., database=)` (Phase 2); `discover_collections(..., database=)` / `describe_collection(..., database=)` (Task 2).
- Produces: each read/introspection tool gains a trailing `database: str | None = None`; the handler computes `db = _resolve_database(ctx, database)` and passes it to the pipeline call.

**Orientation:** run `graphify query "read.py find count aggregate tools pipeline.run params"`; else read `read.py`. Import `_resolve_database` from `._common`. For each tool, add `database: str | None = None` as the LAST parameter and thread `db = _resolve_database(ctx, database)` into: `run(agent, collection, action, params, database=db)` for find/count/aggregate/indexes; `discover_collections(agent, database=db)` for list_collections; `describe_collection(agent, collection, database=db)` for schema.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_read_tools_database.py
import json
import pytest
from mcp.server.fastmcp import FastMCP

from guardmcp.server.tools._common import ToolContext
from guardmcp.server.tools import read as read_tools


class _Pipeline:
    def __init__(self): self.run_calls = []
    _registry = None
    async def run(self, agent, collection, action, params, database=None):
        self.run_calls.append((collection, action.value if hasattr(action, "value") else action, database))
        return {"status": "success", "data": {"count": 0}}
    async def discover_collections(self, agent, database=None):
        self.run_calls.append(("<list>", "list", database)); return []


def _register():
    mcp = FastMCP("t"); pipe = _Pipeline(); box = {"db": None}
    ctx = ToolContext(get_pipeline=lambda: pipe, get_agent=lambda: "claude", get_settings=lambda: None,
                      get_active_database=lambda: box["db"], set_active_database=lambda v: box.__setitem__("db", v))
    read_tools.register(mcp, ctx)
    return mcp, pipe, box


async def _call(mcp, name, **kw):
    return json.loads(await mcp._tool_manager.get_tool(name).fn(**kw))


@pytest.mark.asyncio
async def test_count_threads_per_call_database():
    mcp, pipe, _ = _register()
    await _call(mcp, "mongodb_count", collection="user", filter={}, database="db1")
    assert any(c[0] == "user" and c[2] == "db1" for c in pipe.run_calls)


@pytest.mark.asyncio
async def test_count_uses_active_database_when_omitted():
    mcp, pipe, box = _register(); box["db"] = "sessiondb"
    await _call(mcp, "mongodb_count", collection="user", filter={})
    assert any(c[0] == "user" and c[2] == "sessiondb" for c in pipe.run_calls)
```

> Adapt tool names / call signatures (`mongodb_count` etc.) and the FastMCP invocation to the repo's real ones (mirror `test_mcp_tooling.py`). Keep the database-threading assertion at full strength.

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest tests/unit/test_read_tools_database.py -v`
Expected: FAIL — count tool has no `database` param / db not threaded.

- [ ] **Step 3: Write minimal implementation**

For each read/introspection tool handler in `read.py` (find, count, aggregate, indexes, explain, schema, list_collections): add trailing `database: str | None = None`; at the top compute `db = _resolve_database(ctx, database)`; pass `database=db` to the `pipeline.run(...)` / `discover_collections(...)` / `describe_collection(...)` call. (Do NOT alter param-building or validation logic otherwise.) If `explain` is registered in `meta/explain.py`, apply the same change there.

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest tests/unit/test_read_tools_database.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/guardmcp/server/tools/read.py tests/unit/test_read_tools_database.py
git commit -m "feat(tools): per-call database on read/introspection tools"
```

---

### Task 5: Per-call `database` on write tools

**Files:**
- Modify: `src/guardmcp/server/tools/write.py`
- Modify: `src/guardmcp/server/tools/_common.py` (`_run_with_confirm` gains `database`)
- Test: `tests/unit/test_write_tools_database.py`

**Interfaces:**
- Consumes: `_resolve_database` (Task 1); `_run_with_confirm` (existing).
- Produces:
  - `_run_with_confirm(ctx_or_pipeline args…, database: str | None = None)` threads `database` into `pipeline.evaluate(..., database=)` and `pipeline.execute_approved(...)` / `pipeline._execute_and_build(..., database=)`. (Read its current body; it already routes through `run`/`execute_approved` which are Phase-2 database-aware — thread `database` through.)
  - Each write tool (`insert_one`/`insert_many`/`update_one`/`update_many`/`delete_one`/`delete_many`) gains trailing `database: str | None = None`; computes `db = _resolve_database(ctx, database)`; passes it to `_run_with_confirm(..., database=db)`.

**Orientation:** run `graphify query "_run_with_confirm write.py insert update delete tools"`; else read `_common.py` `_run_with_confirm` and `write.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_write_tools_database.py
import json
import pytest
from mcp.server.fastmcp import FastMCP

from guardmcp.core.models.domain import Decision, DecisionStatus
from guardmcp.server.tools._common import ToolContext
from guardmcp.server.tools import write as write_tools


class _Pipeline:
    def __init__(self): self.eval_calls = []; self._registry = None; self._audit = _A()
    def evaluate(self, agent, collection, action, params, database=None):
        self.eval_calls.append((collection, database))
        from guardmcp.core.pipeline import EvalResult
        from guardmcp.core.models.domain import Request, Action
        return EvalResult(request=Request(agent=agent, collection=collection, action=Action.INSERT_ONE, params=params, database=database),
                          decision=Decision(status=DecisionStatus.DENIED, reason="x", code="POLICY_DENIED"), policy=None)


class _A:
    def build(self, **k): return k
    async def log(self, r): return None


def _register():
    mcp = FastMCP("t"); pipe = _Pipeline(); box = {"db": "sessiondb"}
    ctx = ToolContext(get_pipeline=lambda: pipe, get_agent=lambda: "claude", get_settings=lambda: None,
                      get_active_database=lambda: box["db"], set_active_database=lambda v: box.__setitem__("db", v))
    write_tools.register(mcp, ctx)
    return mcp, pipe


async def _call(mcp, name, **kw):
    return json.loads(await mcp._tool_manager.get_tool(name).fn(**kw))


@pytest.mark.asyncio
async def test_insert_threads_per_call_database():
    mcp, pipe = _register()
    await _call(mcp, "mongodb_insert_one", collection="user", document={"a": 1}, database="db1")
    assert ("user", "db1") in pipe.eval_calls


@pytest.mark.asyncio
async def test_insert_uses_active_database_when_omitted():
    mcp, pipe = _register()
    await _call(mcp, "mongodb_insert_one", collection="user", document={"a": 1})
    assert ("user", "sessiondb") in pipe.eval_calls
```

> Adapt write tool names + the confirm path to the repo's real ones (writes may need a `Context`/elicit stub — mirror how existing write-tool tests call them; if a `ctx: Context` FastMCP param is required, provide a stub as those tests do). Keep the database-threading assertion.

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest tests/unit/test_write_tools_database.py -v`
Expected: FAIL — write tool has no `database` param / not threaded into evaluate.

- [ ] **Step 3: Write minimal implementation**

Add `database: str | None = None` to `_run_with_confirm` (trailing) and thread it into its internal `pipeline.evaluate(..., database=database)` and `pipeline.execute_approved(...)` / `_execute_and_build(..., database=database)` calls. In `write.py`, add trailing `database: str | None = None` to each write tool; compute `db = _resolve_database(ctx, database)`; pass `database=db` to `_run_with_confirm(...)`. Import `_resolve_database` from `._common`.

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest tests/unit/test_write_tools_database.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/guardmcp/server/tools/write.py src/guardmcp/server/tools/_common.py tests/unit/test_write_tools_database.py
git commit -m "feat(tools): per-call database on write tools via _run_with_confirm"
```

---

### Task 6: `list_databases` policy-filter + `guardmcp_status` active/allowed databases

**Files:**
- Modify: `src/guardmcp/server/tools/read.py` (`list_databases` handler)
- Modify: `src/guardmcp/server/tools/meta/status.py` (status payload)
- Test: `tests/unit/test_list_databases_and_status_database.py`

**Interfaces:**
- Produces:
  - `list_databases` result filtered: when the agent's `policy.databases_allow` is non-empty, return only those names (intersected with server-visible databases); empty → return all (back-compat).
  - `guardmcp_status` payload gains `active_database` (from `ctx.get_active_database()`) and `allowed_databases` (from `policy.databases_allow`).

**Orientation:** run `graphify query "list_databases tool status.py payload policy databases_allow"`; else read `read.py` `list_databases` + `meta/status.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_list_databases_and_status_database.py
import json
import pytest
from mcp.server.fastmcp import FastMCP

from guardmcp.core.policy.models import Policy
from guardmcp.server.tools._common import ToolContext
from guardmcp.server.tools import read as read_tools


class _Pipeline:
    def __init__(self, policy, dbs): self._p = policy; self._dbs = dbs; self._registry = None; self._policies = _L(policy)
    async def run(self, agent, collection, action, params, database=None):
        return {"status": "success", "data": {"databases": [{"name": n} for n in self._dbs]}}


class _L:
    def __init__(self, p): self._p = p
    def get(self, a): return self._p


def _register(policy, dbs):
    mcp = FastMCP("t")
    ctx = ToolContext(get_pipeline=lambda: _Pipeline(policy, dbs), get_agent=lambda: "claude",
                      get_settings=lambda: None, get_active_database=lambda: "db1",
                      set_active_database=lambda v: None)
    read_tools.register(mcp, ctx)
    return mcp


async def _call(mcp, name, **kw):
    return json.loads(await mcp._tool_manager.get_tool(name).fn(**kw))


@pytest.mark.asyncio
async def test_list_databases_filtered_to_allowed():
    p = Policy(agent="claude", databases_allow=["db1", "db2"])
    mcp = _register(p, ["db1", "db2", "secret_db"])
    out = await _call(mcp, "mongodb_list_databases")
    names = {d["name"] for d in out["data"]["databases"]}
    assert names == {"db1", "db2"} and "secret_db" not in names
```

> Confirm the real `list_databases` result shape (it returns via `pipeline.run(..., Action.LIST_DATABASES, ...)` → `data.databases`); adapt the filter point + test to the real shape. Add a status test asserting `active_database`/`allowed_databases` appear (mirror the existing status test's harness).

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest tests/unit/test_list_databases_and_status_database.py -v`
Expected: FAIL — `secret_db` present (unfiltered).

- [ ] **Step 3: Write minimal implementation**

In `read.py` `list_databases` handler: after obtaining the result, if the agent's `policy.databases_allow` is non-empty, filter `data["databases"]` to entries whose `name` is in `databases_allow`. Get the policy via `get_pipeline()._policies.get(get_agent())` (or an existing accessor — check how other handlers read the policy). Empty allow → no filtering.

In `meta/status.py`: add `active_database` (from `ctx.get_active_database()`) and `allowed_databases` (from the agent policy's `databases_allow`) to the status payload/stats.

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest tests/unit/test_list_databases_and_status_database.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/guardmcp/server/tools/read.py src/guardmcp/server/tools/meta/status.py tests/unit/test_list_databases_and_status_database.py
git commit -m "feat(tools): policy-filtered list_databases + active/allowed databases in status"
```

---

### Task 7: Integration + back-compat + eval

**Files:**
- Create: `tests/integration/test_multi_db_phase3.py`

**Interfaces:**
- Consumes: everything above via the registered tools.

**Proves:** (1) a per-call `database` reaches `pipeline.run` for a read AND a write tool; (2) `use_database` sets the active db and a subsequent tool with no `database` uses it, and a per-call `database` overrides it; (3) an unlisted database via `use_database` → `DATABASE_NOT_ALLOWED`, active db unchanged; (4) `switch_connection` resets the active db; (5) `list_databases` filtered; (6) full back-compat — with no `databases_allow` and no `database`, tools behave as today.

- [ ] **Step 1: Write the failing/passing test**

Write integration tests exercising the registered read + write tools through a fake pipeline (mirror the Task 3–6 harnesses), asserting the six behaviors above. Reuse the fake-pipeline patterns from the per-task tests. Assert real values (database threaded, active-db resolution order, filtered names, `DATABASE_NOT_ALLOWED` code).

- [ ] **Step 2: Run it**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest tests/integration/test_multi_db_phase3.py -v`
Expected: PASS. If a real product bug surfaces, fix the implicated task (don't weaken the test).

- [ ] **Step 3: Full regression + eval + clean-tree check**

Run: `git status` (MUST be clean — no uncommitted edit masking a committed failure).
Then: `/Users/suresh/guardmcp/.venv/bin/python -m pytest -q --deselect tests/integration/test_transport_lifecycle.py::test_streamable_http_db_tool_survives_session_boundary`
Then eval: `/Users/suresh/guardmcp/.venv/bin/python -m guardmcp.eval evals/cases/` (42/42).
Then `/Users/suresh/guardmcp/.venv/bin/python -m ruff check src tests`.
Expected: ALL PASS — proves single-DB back-compat (existing tool tests + eval unchanged).

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_multi_db_phase3.py
git commit -m "test(multi-db): phase 3 tool-exposure integration + back-compat"
```

---

## Self-Review

**Spec coverage:** active-db holder + resolution (T1); discovery-method database threading (T2, needed by schema/list_collections tools); `use_database` + switch reset (T3); per-call `database` on read/introspection (T4); on writes (T5); filtered `list_databases` + status active/allowed (T6); integration + back-compat + eval (T7). Resolution order per-call→active→default enforced by `_resolve_database` (T1) used by all tool tasks. Cross-database relationships explicitly out of scope (next slice).

**Placeholders:** none — novel code (holder, resolution, `use_database`, discovery threading) is complete; the repetitive per-tool param-threading tasks (T4/T5) give the exact pattern + a worked handler and instruct applying it to each named tool after reading the file (every tool signature must be located in-repo — the change is fully specified). Several steps note "confirm the real tool name / result shape / FastMCP invocation" because the exact registered names + envelopes must match the repo (mirror `test_mcp_tooling.py`).

**Type consistency:** `database: str | None = None` trailing+optional everywhere; `_resolve_database(ctx, per_call) -> str | None` used identically across T4/T5; `use_database_audited(agent, name) -> bool` (T3) consumed by the tool; `discover_collections(agent, database=None)` / `describe_collection(agent, collection, database=None)` (T2) consumed by T4; `_run_with_confirm(..., database=None)` (T5) threads into the Phase-2 `evaluate`/`execute_approved`. `ErrorCode.DATABASE_NOT_ALLOWED` reused. Active-db state on `AppContext`, accessed via `ToolContext.get/set_active_database`.
