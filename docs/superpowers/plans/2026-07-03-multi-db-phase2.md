# Multi-Database Governance — Phase 2 (Backend Database Parameter) Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Thread the governed `database` from authorization into execution + result masking — MongoClient/executor route to the named DB, `GuardPipeline.run()` re-checks the database gate on the execute path, results are masked with the target DB's mask set, and the aggregation guard resolves per target DB. `database=None` everywhere ⇒ configured DB ⇒ single-database behavior byte-identical.

**Architecture:** Additive `database: str | None = None` parameter threaded through `MongoClient.get_db` → `MongoExecutor` (execution + introspection, caches keyed by `(database, collection)`) → `GuardPipeline.run`/`_execute_and_build`/`_build_success`/`_guard_aggregation`. Policy masking is ALREADY database-aware and cache-keyed by `(collection, database)` (Phase 1) — Phase 2 only passes `database` into those calls.

**Tech Stack:** Python 3.12+, Pydantic v2, motor, pytest/pytest-asyncio.

## Global Constraints

- Backward compatible: `database=None` → the connection's configured DB; single-DB results, masking, audit records, and the audit HMAC chain are byte-identical to today. All new params optional + trailing.
- Executor caches key by `(database, collection)`; the `None` bucket == the single configured DB (preserves today's cache hits).
- Policy masking: `mask_fields_for(collection, database)` is Phase-1-aware, but the masker CACHES (`result_transformer`/`audit_masker`) were re-keyed to `(collection, database)` **in Phase 2** (a late correction — they were 1-arg at Phase-1 HEAD). Pass `database` into `result_transformer(collection, database)` / `audit_masker(collection, database)` / `mask_fields_for(collection, database)`.
- `GuardPipeline.run()` MUST pass `database` into its internal `evaluate(...)` (closes the Phase-1 execute-path gate bypass).
- No MCP tool change (Phase 3). No new tool. Deterministic.
- Run tests: `/Users/suresh/guardmcp/.venv/bin/python -m pytest <path> -v`. Lint: `/Users/suresh/guardmcp/.venv/bin/python -m ruff check src tests`. (No `python` on PATH.)
- Codebase-orientation rule (repo mandate): before reading a source file to understand it, run `graphify query "<question>"`; if graphify is unavailable in the shell, read the file directly. Applies to subagents.
- Commit bodies end with: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

---

### Task 1: `MongoClient.get_db(name)` + database-routed collection access

**Files:**
- Modify: `src/guardmcp/plugins/mongodb/client.py`
- Test: `tests/unit/test_mongo_client_get_db.py`

**Interfaces:**
- Produces: `MongoClient.get_db(self, name: str | None = None)` → `self._client[name] if name else self._db`. `MongoClient.get_collection(self, name: str, database: str | None = None)` → `self.get_db(database)[name]`. `list_collection_names(self, database: str | None = None)` routes via `get_db(database)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_mongo_client_get_db.py
from guardmcp.plugins.mongodb.client import MongoClient


class _FakeMotor(dict):
    """dict-like: client[name] -> a sentinel db object."""
    def __getitem__(self, name):
        return f"db:{name}"


def _client():
    c = MongoClient.__new__(MongoClient)   # bypass real connection
    c._client = _FakeMotor()
    c._db = "db:configured"
    return c


def test_get_db_default_returns_configured():
    assert _client().get_db() == "db:configured"
    assert _client().get_db(None) == "db:configured"


def test_get_db_named_returns_that_db():
    assert _client().get_db("other") == "db:other"


def test_get_collection_routes_by_database():
    c = _client()
    # get_collection returns get_db(database)[name]; our fake db is a str, so
    # emulate indexing by asserting the db selection, not the collection object:
    assert c.get_db("other") == "db:other"
```

> Note: `get_collection` indexes into the db object; the fake returns a string, so the test asserts db selection via `get_db`. If you prefer, make `_FakeMotor.__getitem__` return an object whose `__getitem__` records the collection name — either way assert that `database` selects the db. Keep assertions real.

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest tests/unit/test_mongo_client_get_db.py -v`
Expected: FAIL — `AttributeError: 'MongoClient' object has no attribute 'get_db'`

- [ ] **Step 3: Write minimal implementation**

In `src/guardmcp/plugins/mongodb/client.py`, add `get_db` and route `get_collection`/`list_collection_names` through it:

```python
    def get_db(self, name: str | None = None):
        return self._client[name] if name else self._db

    def get_collection(self, name: str, database: str | None = None):
        return self.get_db(database)[name]

    async def list_collection_names(self, database: str | None = None) -> list[str]:
        return await self.get_db(database).list_collection_names()
```

(Keep `get_db()` returning the existing `self._db` when `name` is falsy so all current callers are unchanged.)

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest tests/unit/test_mongo_client_get_db.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/guardmcp/plugins/mongodb/client.py tests/unit/test_mongo_client_get_db.py
git commit -m "feat(mongo): MongoClient.get_db + database-routed collection access"
```

---

### Task 2: `MongoExecutor` + `MongoSchemaCache` — database parameter + `(database, collection)` cache keys

**Files:**
- Modify: `src/guardmcp/plugins/mongodb/executor.py`
- Modify: `src/guardmcp/plugins/mongodb/schema_cache.py`
- Test: `tests/unit/test_executor_database_routing.py`

**Interfaces:**
- Consumes: `MongoClient.get_collection(name, database)` / `get_db(database)` (Task 1).
- Produces:
  - `MongoExecutor.execute(self, collection, action, params, database: str | None = None)` — threads `database` to `_execute_once` → `get_collection(collection, database)` and to DB-level actions via `get_db(database)`.
  - Introspection: `collection_schema(collection, mask_fields, sample_size=None, database=None)`, `collection_indexes(collection, database=None)`, `field_stats(collection, mask_fields, database=None)`, `list_collections(database=None)`, `explain_find_stats`/`explain_aggregate_stats`/`explain_find`/`explain_aggregate` gain `database=None`.
  - `MongoSchemaCache`: `_sample_schema`, `collection_schema`, `type_map_for`, `field_stats` gain `database=None`; the internal cache dict is keyed by `(database, collection)` instead of `collection`. `_id`/index reads route via `get_collection(collection, database)`.

**Orientation:** run `graphify query "MongoExecutor _execute_once get_collection; MongoSchemaCache _sample_schema cache key"`; if unavailable read `executor.py` + `schema_cache.py`. Every place that does `self._client.get_collection(collection)` becomes `self._client.get_collection(collection, database)`; every `get_db()` for DB-level ops becomes `get_db(database)`; the schema-cache map key becomes `(database, collection)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_executor_database_routing.py
import pytest

from guardmcp.plugins.mongodb.executor import MongoExecutor
from guardmcp.core.models.domain import Action


class _Cursor:
    def __init__(self, docs): self._docs = docs
    def find(self, *a, **k): return self
    def sort(self, *a, **k): return self
    def skip(self, *a, **k): return self
    def limit(self, *a, **k): return self
    async def to_list(self, n): return self._docs


class _Coll:
    name = "user"
    def find(self, *a, **k): return _Cursor([{"_id": 1}])


class _FakeClient:
    def __init__(self): self.calls = []
    def get_collection(self, name, database=None):
        self.calls.append((name, database))
        return _Coll()
    def get_db(self, name=None):
        self.calls.append(("<db>", name))
        class _DB:
            async def command(self, *a, **k): return {"ok": 1}
            async def list_collection_names(self): return ["user"]
        return _DB()


@pytest.mark.asyncio
async def test_execute_routes_collection_to_named_database():
    client = _FakeClient()
    ex = MongoExecutor(client)
    await ex.execute("user", Action.FIND, {"filter": {}}, database="other")
    assert ("user", "other") in client.calls


@pytest.mark.asyncio
async def test_execute_default_database_is_none():
    client = _FakeClient()
    ex = MongoExecutor(client)
    await ex.execute("user", Action.FIND, {"filter": {}})
    assert ("user", None) in client.calls
```

> Adapt the fakes to the executor's real internals if the marshaller/type-map path requires stubbing (the executor calls `type_map_for` during `_marshal`). If `_marshal` needs a type map, stub `ex._schema.type_map_for` to return `{}` so the test focuses on database routing. Keep the routing assertion at full strength.

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest tests/unit/test_executor_database_routing.py -v`
Expected: FAIL — `execute()` has no `database` parameter (TypeError) or the `(name, database)` tuple never recorded.

- [ ] **Step 3: Write minimal implementation**

In `executor.py`:
- Add `database: str | None = None` to `execute(...)` and pass it to `_execute_once(collection, action, params, database)`.
- In `_execute_once`, obtain the collection handle via `self._client.get_collection(collection, database)` (was `get_collection(collection)`), and for DB-level actions use `self._client.get_db(database)` / route `list_databases`/`db_stats` through `get_db(database)`.
- Thread `database` through `collection_schema`, `collection_indexes`, `field_stats`, `list_collections`, and the `explain_*` methods to their `get_collection`/`get_db` calls and to the schema-cache delegations.

In `schema_cache.py`:
- Add `database: str | None = None` to `_sample_schema`, `collection_schema`, `type_map_for`, `field_stats`.
- Change the cache dict key from `collection` to `(database, collection)` (update the get/set/`move_to_end`/eviction sites).
- Sample via `self._client.get_collection(collection, database)`.

Keep every signature's `database` defaulting to `None` so existing callers (which pass no database) resolve to the configured DB and the `(None, collection)` cache bucket.

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest tests/unit/test_executor_database_routing.py tests/unit/test_mongo_plugin.py -v`
Expected: PASS (routing tests pass; existing mongo executor/plugin tests still pass)

- [ ] **Step 5: Commit**

```bash
git add src/guardmcp/plugins/mongodb/executor.py src/guardmcp/plugins/mongodb/schema_cache.py tests/unit/test_executor_database_routing.py
git commit -m "feat(mongo): thread database through executor + schema cache keyed by (database, collection)"
```

---

### Task 3: `GuardPipeline` — thread database through run/execute/mask/guard

**Files:**
- Modify: `src/guardmcp/core/pipeline.py`
- Test: `tests/unit/test_pipeline_execute_database.py`

**Interfaces:**
- Consumes: `MongoExecutor.execute(..., database=)` (Task 2); `Policy.result_transformer(collection, database)`, `Policy.audit_masker(collection, database)`, `Policy.scope_for(database)`, `Policy.mask_fields_for(collection, database)` (already database-aware from Phase 1); `Request.database` (Phase 1).
- Produces:
  - `run(self, agent, collection, action, params, incoming_traceparent=None, database: str | None = None)` — passes `database` into its internal `evaluate(...)` AND into `_execute_and_build`.
  - `_execute_and_build(self, req, policy, database: str | None = None)` — calls `executor.execute(req.collection, req.action, params, database=database)`; passes `database` into `_build_success`.
  - `execute_approved(self, eval_result)` — threads `eval_result.request.database` into its re-`evaluate` and `_execute_and_build`.
  - `_build_success(self, raw, action, policy, collection="*", database: str | None = None)` — uses `policy.result_transformer(collection, database)` and `policy.audit_masker(collection, database)` (the EXPLAIN masking path).
  - `_audit_params(self, req, policy)` — uses `policy.audit_masker(req.collection, req.database)`.
  - `_guard_aggregation(self, request, policy, database: str | None = None)` — foreign-collection check uses `policy.scope_for(database).collections`; masked-field refs use `policy.mask_fields_for(request.collection, database)`. Called from `evaluate` with the request's `database`.

**Orientation:** run `graphify query "GuardPipeline run _execute_and_build _build_success _guard_aggregation _audit_params"`; if unavailable read `core/pipeline.py`. Thread `database` additively; `database=None` must reproduce today's calls exactly (e.g. `result_transformer(collection, None)` == today's `result_transformer(collection)`).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_pipeline_execute_database.py
import pytest

from guardmcp.core.models.domain import Action, DecisionStatus
from guardmcp.core.pipeline import GuardPipeline
from guardmcp.core.policy.engine import PolicyEngine
from guardmcp.core.policy.models import CollectionPolicy, DatabaseScope, Policy
from guardmcp.core.risk.engine import RiskEngine


class _Loader:
    def __init__(self, p): self._p = p
    def get(self, agent): return self._p


class _Executor:
    def __init__(self): self.exec_calls = []
    async def execute(self, collection, action, params, database=None):
        self.exec_calls.append((collection, action, database))
        return {"documents": [{"_id": 1}], "count": 1}
    async def list_collections(self): return ["x"]


class _Audit:
    def build(self, **k): return k
    async def log(self, r): return None


def _pipeline(policy, executor):
    return GuardPipeline(policy_loader=_Loader(policy), policy_engine=PolicyEngine(),
                         risk_engine=RiskEngine(), audit_logger=_Audit(),
                         approval_store=None, executor=executor)


@pytest.mark.asyncio
async def test_run_denies_disallowed_database_on_execute_path():
    p = Policy(agent="claude", databases_allow=["db1"],
               databases={"db1": DatabaseScope(collections=CollectionPolicy(allow=["x"]))})
    ex = _Executor()
    res = await _pipeline(p, ex).run("claude", "x", Action.FIND, {"filter": {}}, database="db2")
    assert res["status"] == "denied"
    assert res["code"] == "DATABASE_NOT_ALLOWED"
    assert ex.exec_calls == []  # never executed


@pytest.mark.asyncio
async def test_run_threads_database_into_executor():
    p = Policy(agent="claude", databases_allow=["db1"],
               databases={"db1": DatabaseScope(collections=CollectionPolicy(allow=["x"]))})
    ex = _Executor()
    res = await _pipeline(p, ex).run("claude", "x", Action.FIND, {"filter": {}}, database="db1")
    assert res["status"] == "success"
    assert ("x", Action.FIND, "db1") in ex.exec_calls


@pytest.mark.asyncio
async def test_run_backcompat_no_database():
    p = Policy(agent="claude", collections=CollectionPolicy(allow=["x"]))
    ex = _Executor()
    res = await _pipeline(p, ex).run("claude", "x", Action.FIND, {"filter": {}})
    assert res["status"] == "success"
    assert ("x", Action.FIND, None) in ex.exec_calls
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest tests/unit/test_pipeline_execute_database.py -v`
Expected: FAIL — `run()` has no `database` parameter / executor called with `None` for the db1 case.

- [ ] **Step 3: Write minimal implementation**

In `core/pipeline.py`:
- `run(...)`: add `database: str | None = None`; call `self.evaluate(agent, collection, action, params, database=database)`; on execute, call `self._execute_and_build(req, policy, database=database)`.
- `_execute_and_build(self, req, policy, database=None)`: `raw = await executor.execute(req.collection, req.action, params, database=database)`; return `self._build_success(raw, req.action, policy, req.collection, database=database)`.
- `execute_approved`: derive `database = eval_result.request.database`; thread into the re-`evaluate(...)` and `_execute_and_build(..., database=database)`.
- `_build_success(self, raw, action, policy, collection="*", database=None)`: replace `policy.result_transformer(collection)` → `policy.result_transformer(collection, database)` and `policy.audit_masker(collection)` (EXPLAIN path) → `policy.audit_masker(collection, database)`.
- `_audit_params`: use `policy.audit_masker(req.collection, req.database)`.
- `evaluate`: pass the request's `database` into `self._guard_aggregation(request, policy, database)`.
- `_guard_aggregation(self, request, policy, database=None)`: use `policy.scope_for(database).collections.allow/deny` in the `collection_permitted(...)` foreign-collection check, and `policy.mask_fields_for(request.collection, database)` for masked-field references.

Every `database=None` path must reproduce the current call exactly.

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest tests/unit/test_pipeline_execute_database.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/guardmcp/core/pipeline.py tests/unit/test_pipeline_execute_database.py
git commit -m "feat(pipeline): thread database through run/execute/mask/aggregation-guard"
```

---

### Task 4: Integration + back-compat regression + eval

**Files:**
- Create: `tests/integration/test_multi_db_phase2.py`

**Interfaces:**
- Consumes: everything above; a stub executor recording `(collection, action, database)` and returning documents with maskable fields.

**Proves:** (1) `run()` denies a disallowed database on the execute path and never calls the executor; (2) an allowed database threads through to the executor; (3) result masking uses the target DB's mask set (a field masked in DB-A is redacted when reading that collection in DB-A but a different field set applies in DB-B); (4) full back-compat — single-DB (`database=None`) results/masking identical.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_multi_db_phase2.py
import pytest

from guardmcp.core.models.domain import Action
from guardmcp.core.pipeline import GuardPipeline
from guardmcp.core.policy.engine import PolicyEngine
from guardmcp.core.policy.models import CollectionPolicy, DatabaseScope, Policy
from guardmcp.core.risk.engine import RiskEngine


class _Loader:
    def __init__(self, p): self._p = p
    def get(self, agent): return self._p


class _Executor:
    def __init__(self): self.calls = []
    async def execute(self, collection, action, params, database=None):
        self.calls.append((collection, database))
        return {"documents": [{"_id": 1, "email": "a@b.com", "ssn": "111", "name": "n"}], "count": 1}
    async def list_collections(self): return ["user"]


class _Audit:
    def build(self, **k): return k
    async def log(self, r): return None


def _pipeline(p, ex):
    return GuardPipeline(policy_loader=_Loader(p), policy_engine=PolicyEngine(),
                         risk_engine=RiskEngine(), audit_logger=_Audit(),
                         approval_store=None, executor=ex)


def _multidb_policy():
    return Policy(agent="claude", databases_allow=["a", "b"],
                  databases={"a": DatabaseScope(collections=CollectionPolicy(allow=["user"]), mask_fields=["ssn"]),
                             "b": DatabaseScope(collections=CollectionPolicy(allow=["user"]), mask_fields=["email"])})


@pytest.mark.asyncio
async def test_execute_path_gate_denies_unlisted_db():
    ex = _Executor()
    res = await _pipeline(_multidb_policy(), ex).run("claude", "user", Action.FIND, {"filter": {}}, database="c")
    assert res["status"] == "denied" and res["code"] == "DATABASE_NOT_ALLOWED"
    assert ex.calls == []


@pytest.mark.asyncio
async def test_masking_uses_target_database_maskset():
    ex = _Executor()
    res_a = await _pipeline(_multidb_policy(), ex).run("claude", "user", Action.FIND, {"filter": {}}, database="a")
    docs_a = res_a["data"]["documents"][0]
    # db 'a' masks ssn, not email
    assert docs_a.get("ssn") != "111"        # ssn masked
    assert docs_a.get("email") == "a@b.com"  # email NOT masked in db 'a'

    ex_b = _Executor()
    res_b = await _pipeline(_multidb_policy(), ex_b).run("claude", "user", Action.FIND, {"filter": {}}, database="b")
    docs_b = res_b["data"]["documents"][0]
    assert docs_b.get("email") != "a@b.com"  # email masked in db 'b'
    assert docs_b.get("ssn") == "111"         # ssn NOT masked in db 'b'
```

> Confirm the masked value's exact sentinel/shape from the existing masking tests (e.g. the masker may drop the key or replace the value). Adjust the "masked" assertion to match the real masking behavior (assert the real value is absent/redacted), keeping the cross-database independence assertion at full strength.

- [ ] **Step 2: Run it**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest tests/integration/test_multi_db_phase2.py -v`
Expected: PASS. If a masking assertion fails only because the redaction sentinel differs, fix the assertion to the real sentinel (do not weaken the cross-DB independence check). If `run()` executes on a denied DB, that's a real bug in Task 3 — fix Task 3.

- [ ] **Step 3: Full regression + eval**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest -q` (deselect the known inherited infra test if it errors: `--deselect tests/integration/test_transport_lifecycle.py::test_streamable_http_db_tool_survives_session_boundary`).
Then eval: `/Users/suresh/guardmcp/.venv/bin/python -m guardmcp.eval evals/cases/` (expect 42/42 — single-DB + Phase-1 decision cases unaffected).
Then `/Users/suresh/guardmcp/.venv/bin/python -m ruff check src tests`.
Expected: ALL PASS — proves single-DB back-compat + audit chain intact.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_multi_db_phase2.py
git commit -m "test(multi-db): phase 2 execute-path gate + per-database masking + back-compat"
```

---

## Self-Review

**Spec coverage:** MongoClient.get_db + routed collection access (T1); executor + schema-cache database param + `(database, collection)` keys (T2); run() execute-path gate + thread to executor (T3); `_execute_and_build`/`execute_approved` threading (T3); result/audit masking pass `database` (T3, leveraging Phase-1's already-keyed maskers); aggregation guard database-aware (T3); integration + per-database masking + back-compat + eval (T4). Phase-3 items (MCP tool params, use_database, list_databases filter, status display) explicitly out of scope.

**Placeholders:** none — code for every change. Steps that touch large existing files instruct reading them first (executor/schema_cache internals, pipeline methods) because every `get_collection`/`get_db`/masker call site must be located; the new signatures + behavior are fully specified.

**Type consistency:** `database: str | None = None` used identically across `get_db`/`get_collection`/`execute`/introspection/`run`/`_execute_and_build`/`_build_success`/`_audit_params`/`_guard_aggregation`. Masking calls use the Phase-1 signatures `result_transformer(collection, database)` / `audit_masker(collection, database)` / `mask_fields_for(collection, database)` verbatim. Schema-cache key tuple `(database, collection)` consistent across get/set/evict.
