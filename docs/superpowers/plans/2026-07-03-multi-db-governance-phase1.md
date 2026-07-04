# Multi-Database Governance — Phase 1 (Governance Core) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make GuardMCP's authorization aware of a `database` axis — policy gains per-database scoping (`databases_allow`, `databases`, `default`), evaluation enforces database allow/deny and resolves the right collection/mask/field rules per database, and audit records the database — with ZERO backend change and identical behavior for existing single-database policies.

**Architecture:** Additive policy model (`DatabaseScope` + resolution via `Policy.scope_for`), a database-aware `PolicyEngine.evaluate` (reads a resolved scope's collections instead of the flat `policy.collections`), and a database gate + audit field in `GuardPipeline.evaluate`. When `database is None` (today's callers), everything resolves to the existing flat policy — behavior is byte-identical.

**Tech Stack:** Python 3.12+, Pydantic v2, pytest.

## Global Constraints

- Backward compatible: a policy with NO `databases`/`databases_allow`/`default` behaves exactly as today; all new params default such that `database=None` ⇒ current behavior. Existing tests must stay green.
- Deny-by-default on the database axis: non-empty `databases_allow` + a database not in it ⇒ DENIED + audited. Empty `databases_allow` ⇒ database axis not enforced (single-DB back-compat).
- Resolution precedence for a database's rules: per-database block → `default` block → flat top-level policy fields.
- No backend/executor/Mongo change in Phase 1. No new MCP tool. Database is not yet threaded from tools — it is a new optional parameter on evaluate, tested directly.
- `mask_fields` keeps its existing flat-`list[str]` OR `dict[str,list[str]]` shape; per-database `mask_fields` reuses the same shape.
- Deterministic; no LLM.
- Run tests: `/Users/suresh/guardmcp/.venv/bin/python -m pytest <path> -v`. Lint: `/Users/suresh/guardmcp/.venv/bin/python -m ruff check src tests`. (No `python` on PATH — always use the venv interpreter.)
- Codebase-orientation rule (repo mandate): before reading a source file to understand it, run `graphify query "<question>"`; if graphify is unavailable in the shell, read the specific file directly. Applies to subagents.
- Commit bodies end with: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

---

### Task 1: Policy model — `DatabaseScope`, database fields, `scope_for`, database-aware `mask_fields_for`

**Files:**
- Modify: `src/guardmcp/core/policy/models.py`
- Test: `tests/unit/test_policy_database_scope.py`

**Interfaces:**
- Consumes: existing `CollectionPolicy`, `Policy` (with `collections`, `mask_fields`, `fields_allow`, `mask_fields_for(collection)`).
- Produces:
  - `class DatabaseScope(BaseModel)`: `collections: CollectionPolicy = CollectionPolicy()`, `mask_fields: list[str] | dict[str, list[str]] = []`, `fields_allow: list[str] = []`.
  - `class ResolvedScope` (dataclass): `collections: CollectionPolicy`, `mask_fields: list|dict`, `fields_allow: list[str]`.
  - New `Policy` fields: `databases_allow: list[str] = []`, `databases: dict[str, DatabaseScope] = {}`, `default_database_scope: DatabaseScope | None = Field(default=None, alias="default")`.
  - `Policy.database_permitted(self, database: str | None) -> bool`.
  - `Policy.scope_for(self, database: str | None) -> ResolvedScope`.
  - `Policy.mask_fields_for(self, collection: str, database: str | None = None) -> list[str]` (extended signature; `database=None` keeps today's behavior).

**Resolution rules:**
- `database_permitted`: `True` if `databases_allow` is empty (back-compat); else `database in databases_allow`. `database=None` → `True` (no axis).
- `scope_for(None)` OR when policy has no database config (`not databases and default_database_scope is None`): return `ResolvedScope(collections=self.collections, mask_fields=self.mask_fields, fields_allow=self.fields_allow)` (flat).
- Otherwise: `block = self.databases.get(database) or self.default_database_scope`. If `block is None` → flat. Else resolve each field, falling back to flat top-level when the block's piece is "empty":
  - collections: `block.collections` if `block.collections.allow or block.collections.deny` else `self.collections`.
  - mask_fields: `block.mask_fields` if `block.mask_fields` else `self.mask_fields`.
  - fields_allow: `block.fields_allow` if `block.fields_allow` else `self.fields_allow`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_policy_database_scope.py
from guardmcp.core.policy.models import CollectionPolicy, DatabaseScope, Policy


def _pol(**kw):
    return Policy(agent="claude", **kw)


def test_backcompat_no_database_config_uses_flat():
    p = _pol(collections=CollectionPolicy(allow=["user"]), mask_fields=["email"])
    assert p.database_permitted(None) is True
    assert p.database_permitted("anydb") is True  # no databases_allow => not enforced
    sc = p.scope_for(None)
    assert sc.collections.allow == ["user"]
    assert p.mask_fields_for("user") == ["email"]


def test_databases_allow_denies_unlisted():
    p = _pol(databases_allow=["db1"])
    assert p.database_permitted("db1") is True
    assert p.database_permitted("db2") is False


def test_scope_for_uses_per_database_block():
    p = _pol(
        databases_allow=["db1", "db2"],
        databases={
            "db1": DatabaseScope(collections=CollectionPolicy(allow=["a"]), mask_fields=["x"]),
            "db2": DatabaseScope(collections=CollectionPolicy(allow=["b"])),
        },
    )
    assert p.scope_for("db1").collections.allow == ["a"]
    assert p.mask_fields_for("a", database="db1") == ["x"]
    assert p.scope_for("db2").collections.allow == ["b"]


def test_scope_for_falls_back_to_default_block():
    p = Policy(agent="claude", databases_allow=["db1", "dbx"],
               databases={"db1": DatabaseScope(collections=CollectionPolicy(allow=["a"]))},
               **{"default": DatabaseScope(collections=CollectionPolicy(allow=["z"]), mask_fields=["m"])})
    # dbx has no explicit block -> default
    assert p.scope_for("dbx").collections.allow == ["z"]
    assert p.mask_fields_for("anything", database="dbx") == ["m"]


def test_block_empty_piece_falls_back_to_flat():
    p = _pol(collections=CollectionPolicy(allow=["flat"]), mask_fields=["fm"],
             databases_allow=["db1"],
             databases={"db1": DatabaseScope(fields_allow=["only"])})  # no collections/mask in block
    sc = p.scope_for("db1")
    assert sc.collections.allow == ["flat"]   # fell back
    assert sc.fields_allow == ["only"]         # from block
    assert p.mask_fields_for("x", database="db1") == ["fm"]  # fell back
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest tests/unit/test_policy_database_scope.py -v`
Expected: FAIL — `ImportError: cannot import name 'DatabaseScope'`

- [ ] **Step 3: Write minimal implementation**

Orientation: run `graphify query "Policy mask_fields_for implementation"`; if unavailable, read `src/guardmcp/core/policy/models.py` to find the existing `mask_fields_for` and the `_resolve_mask` logic it uses (flat list vs dict with `"*"` bucket). You will (a) add the models/fields/methods below and (b) extend `mask_fields_for` to accept `database` and resolve via `scope_for`.

Add to `src/guardmcp/core/policy/models.py`:

```python
from dataclasses import dataclass


class DatabaseScope(BaseModel):
    collections: CollectionPolicy = CollectionPolicy()
    mask_fields: list[str] | dict[str, list[str]] = []
    fields_allow: list[str] = []


@dataclass
class ResolvedScope:
    collections: CollectionPolicy
    mask_fields: "list[str] | dict[str, list[str]]"
    fields_allow: list[str]
```

Add these fields to `Policy` (near `collections`/`mask_fields`):

```python
    databases_allow: list[str] = []
    databases: dict[str, DatabaseScope] = {}
    default_database_scope: DatabaseScope | None = Field(default=None, alias="default")
```

Add these methods to `Policy`:

```python
    def _has_db_config(self) -> bool:
        return bool(self.databases) or self.default_database_scope is not None or bool(self.databases_allow)

    def database_permitted(self, database: str | None) -> bool:
        if database is None or not self.databases_allow:
            return True
        return database in self.databases_allow

    def scope_for(self, database: str | None) -> ResolvedScope:
        flat = ResolvedScope(
            collections=self.collections, mask_fields=self.mask_fields, fields_allow=self.fields_allow
        )
        if database is None or not self._has_db_config():
            return flat
        block = self.databases.get(database) or self.default_database_scope
        if block is None:
            return flat
        cols = block.collections if (block.collections.allow or block.collections.deny) else self.collections
        mask = block.mask_fields if block.mask_fields else self.mask_fields
        fa = block.fields_allow if block.fields_allow else self.fields_allow
        return ResolvedScope(collections=cols, mask_fields=mask, fields_allow=fa)
```

Extend `mask_fields_for`: locate the existing method (it resolves `self.mask_fields` flat-or-dict for a collection). Refactor it so the mask source is `self.scope_for(database).mask_fields` instead of `self.mask_fields`, keeping the identical flat/dict resolution. New signature `def mask_fields_for(self, collection: str, database: str | None = None) -> list[str]`. When `database is None`, `scope_for(None)` returns the flat mask_fields, so existing behavior is preserved.

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest tests/unit/test_policy_database_scope.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/guardmcp/core/policy/models.py tests/unit/test_policy_database_scope.py
git commit -m "feat(policy): per-database scope model + scope_for + database-aware mask_fields_for"
```

---

### Task 2: `PolicyEngine.evaluate` — database-aware collection check

**Files:**
- Modify: `src/guardmcp/core/policy/engine.py`
- Modify: `src/guardmcp/core/interfaces/errors.py` (add `DATABASE_NOT_ALLOWED`)
- Test: `tests/unit/test_policy_engine_database.py`

**Interfaces:**
- Consumes: `Policy.scope_for` (Task 1), `collection_permitted`, `Request`, `Decision`, `RiskLevel`.
- Produces: `PolicyEngine.evaluate(self, request, policy, risk, trace=None, database: str | None = None) -> Decision` — the collection allow/deny check uses `policy.scope_for(database).collections` instead of `policy.collections`. Everything else unchanged. New `ErrorCode.DATABASE_NOT_ALLOWED`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_policy_engine_database.py
from guardmcp.core.models.domain import Action, DecisionStatus, Request, RiskLevel
from guardmcp.core.policy.engine import PolicyEngine
from guardmcp.core.policy.models import CollectionPolicy, DatabaseScope, Policy

E = PolicyEngine()


def _req(collection):
    return Request(agent="claude", collection=collection, action=Action.FIND, params={})


def test_none_database_uses_flat_collections():
    p = Policy(agent="claude", collections=CollectionPolicy(allow=["user"]))
    assert E.evaluate(_req("user"), p, RiskLevel.LOW).status == DecisionStatus.ALLOWED
    assert E.evaluate(_req("secret"), p, RiskLevel.LOW).status == DecisionStatus.DENIED


def test_collection_allowed_in_one_db_denied_in_another():
    p = Policy(agent="claude", databases_allow=["db1", "db2"],
               databases={"db1": DatabaseScope(collections=CollectionPolicy(allow=["x"])),
                          "db2": DatabaseScope(collections=CollectionPolicy(allow=["y"]))})
    assert E.evaluate(_req("x"), p, RiskLevel.LOW, database="db1").status == DecisionStatus.ALLOWED
    assert E.evaluate(_req("x"), p, RiskLevel.LOW, database="db2").status == DecisionStatus.DENIED
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest tests/unit/test_policy_engine_database.py -v`
Expected: FAIL — `TypeError: evaluate() got an unexpected keyword argument 'database'`

- [ ] **Step 3: Write minimal implementation**

In `src/guardmcp/core/interfaces/errors.py`, add a member to the `ErrorCode` enum (match the existing style/values):

```python
    DATABASE_NOT_ALLOWED = "DATABASE_NOT_ALLOWED"
```

In `src/guardmcp/core/policy/engine.py`, change the signature to add `database: str | None = None`, and resolve the scope once at the top of `evaluate`:

```python
    def evaluate(self, request, policy, risk, trace=None, database: str | None = None):
        scope = policy.scope_for(database)
        ...
```

Then in the collection check (Rules 2–3) replace `policy.collections.allow` / `policy.collections.deny` with `scope.collections.allow` / `scope.collections.deny` (both in the `collection_permitted(...)` call and the deny-list membership/`Allowed:` message). Leave mode/actions/approval rules unchanged.

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest tests/unit/test_policy_engine_database.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/guardmcp/core/policy/engine.py src/guardmcp/core/interfaces/errors.py tests/unit/test_policy_engine_database.py
git commit -m "feat(policy): database-aware collection check in PolicyEngine.evaluate"
```

---

### Task 3: `GuardPipeline.evaluate` — database gate + thread database + audit field

**Files:**
- Modify: `src/guardmcp/core/models/domain.py` (add `Request.database`)
- Modify: `src/guardmcp/core/pipeline.py` (`evaluate` + `_audit_event`)
- Test: `tests/unit/test_pipeline_database_gate.py`

**Interfaces:**
- Consumes: `Policy.database_permitted`/`scope_for` (Task 1), `PolicyEngine.evaluate(..., database=)` (Task 2), `ErrorCode.DATABASE_NOT_ALLOWED`.
- Produces:
  - `Request.database: str | None = None` (additive field).
  - `GuardPipeline.evaluate(self, agent, collection, action, params, trace=None, policy_override=None, database: str | None = None) -> EvalResult`. Behavior: after resolving `policy`, if `not policy.database_permitted(database)` → DENIED (`ErrorCode.DATABASE_NOT_ALLOWED`) with a trace step; else pass `database` through to `policy_engine.evaluate`. `Request` is built with `database=database`.
  - `_audit_event(..., database: str | None = None)` includes the database in the record (additive; default None keeps existing records unchanged).

**Orientation:** run `graphify query "GuardPipeline evaluate audit_event AuditLogger build"`; if unavailable, read `src/guardmcp/core/pipeline.py` (`evaluate`, `_audit_event`) and `src/guardmcp/core/audit/logger.py` (`build` signature) to add the optional `database` kwarg additively.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_pipeline_database_gate.py
from guardmcp.core.models.domain import Action, DecisionStatus
from guardmcp.core.pipeline import GuardPipeline
from guardmcp.core.policy.engine import PolicyEngine
from guardmcp.core.policy.models import CollectionPolicy, DatabaseScope, Policy
from guardmcp.core.risk.engine import RiskEngine


class _Loader:
    def __init__(self, policy):
        self._p = policy
    def get(self, agent):
        return self._p


def _pipeline(policy):
    return GuardPipeline(
        policy_loader=_Loader(policy), policy_engine=PolicyEngine(), risk_engine=RiskEngine(),
        audit_logger=None, approval_store=None, executor=None,
    )


def test_disallowed_database_denied():
    p = Policy(agent="claude", databases_allow=["db1"],
               databases={"db1": DatabaseScope(collections=CollectionPolicy(allow=["x"]))})
    res = _pipeline(p).evaluate("claude", "x", Action.FIND, {}, database="db2")
    assert res.decision.status == DecisionStatus.DENIED
    assert res.decision.code == "DATABASE_NOT_ALLOWED"


def test_allowed_database_resolves_scope():
    p = Policy(agent="claude", databases_allow=["db1"],
               databases={"db1": DatabaseScope(collections=CollectionPolicy(allow=["x"]))})
    res = _pipeline(p).evaluate("claude", "x", Action.FIND, {}, database="db1")
    assert res.decision.status == DecisionStatus.ALLOWED
    assert res.request.database == "db1"


def test_none_database_backcompat():
    p = Policy(agent="claude", collections=CollectionPolicy(allow=["x"]))
    res = _pipeline(p).evaluate("claude", "x", Action.FIND, {})
    assert res.decision.status == DecisionStatus.ALLOWED
    assert res.request.database is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest tests/unit/test_pipeline_database_gate.py -v`
Expected: FAIL — `TypeError: evaluate() got an unexpected keyword argument 'database'`

- [ ] **Step 3: Write minimal implementation**

In `src/guardmcp/core/models/domain.py`, add to the `Request` model (additive, default None):

```python
    database: str | None = None
```

In `src/guardmcp/core/pipeline.py` `evaluate`: add `database: str | None = None` to the signature; build the `Request` with `database=database`; after the policy is resolved (and not None), before the aggregation/risk checks, insert the database gate:

```python
        if not policy.database_permitted(database):
            if trace is not None:
                trace.add("policy", "database_access", "matched",
                          f"database '{database}' not permitted by policy")
            return EvalResult(
                request=request,
                decision=Decision(
                    status=DecisionStatus.DENIED,
                    reason=f"database '{database}' is not permitted by policy.",
                    code=ErrorCode.DATABASE_NOT_ALLOWED.value,
                ),
                policy=policy,
            )
```

Pass `database` into the engine call: `decision = self._policy_engine.evaluate(request, policy, risk, trace=trace, database=database)`. (`ErrorCode` is already imported in pipeline.py.)

In `_audit_event`, add `database: str | None = None` to the signature and pass it into `self._audit.build(...)`. In `src/guardmcp/core/audit/logger.py`, add `database: str | None = None` to `build(...)` and include it in the record dict (additive — default None so existing records/HMAC chain for single-DB callers are unchanged).

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest tests/unit/test_pipeline_database_gate.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/guardmcp/core/models/domain.py src/guardmcp/core/pipeline.py src/guardmcp/core/audit/logger.py tests/unit/test_pipeline_database_gate.py
git commit -m "feat(pipeline): database gate + thread database through evaluate + audit"
```

---

### Task 4: Back-compat regression + adversarial integration

**Files:**
- Create: `tests/integration/test_multi_db_governance.py`

**Interfaces:**
- Consumes: everything above.

**Proves:** (1) a collection allowed in DB-A is denied when the same request targets DB-B; (2) masked fields resolve independently per database; (3) an unlisted database is denied with `DATABASE_NOT_ALLOWED`; (4) a flat (no-`databases`) policy behaves identically with and without `database=None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_multi_db_governance.py
from guardmcp.core.policy.models import CollectionPolicy, DatabaseScope, Policy


def test_masking_independent_per_database():
    p = Policy(agent="claude", databases_allow=["a", "b"],
               databases={"a": DatabaseScope(collections=CollectionPolicy(allow=["*"]), mask_fields=["ssn"]),
                          "b": DatabaseScope(collections=CollectionPolicy(allow=["*"]), mask_fields=["email"])})
    assert p.mask_fields_for("user", database="a") == ["ssn"]
    assert p.mask_fields_for("user", database="b") == ["email"]


def test_flat_policy_identical_with_none_database():
    p = Policy(agent="claude", collections=CollectionPolicy(allow=["user"]), mask_fields=["email"])
    assert p.scope_for(None).collections.allow == p.collections.allow
    assert p.mask_fields_for("user") == p.mask_fields_for("user", database=None) == ["email"]
    assert p.database_permitted("whatever") is True
```

Add an engine-level adversarial case (reuse `PolicyEngine` from Task 2's test style): collection `x` allowed only in `db1`; assert `evaluate(_req("x"), p, LOW, database="db1")` ALLOWED and `database="db2"` DENIED; and an unlisted `database="db3"` gated at the pipeline (reuse Task 3's `_pipeline`) returns `DATABASE_NOT_ALLOWED`.

- [ ] **Step 2: Run it**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest tests/integration/test_multi_db_governance.py -v`
Expected: PASS (exercises already-built code). If any FAIL, fix the implicated task (don't weaken the test); if it's a fixture mistake, fix the fixture.

- [ ] **Step 3: Full regression**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest -q`
Expected: ALL PASS — especially the existing policy/engine/pipeline suites (proves single-DB back-compat). Then `/Users/suresh/guardmcp/.venv/bin/python -m ruff check src tests`.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_multi_db_governance.py
git commit -m "test(policy): multi-database governance back-compat + adversarial"
```

---

## Self-Review

**Spec coverage (Phase 1 scope):** `databases_allow` + `databases` + `default` model (T1), `scope_for` precedence per-db→default→flat (T1), database-aware `mask_fields_for` (T1), deny-by-default database gate + audit (T2 error code, T3 gate+audit), database-aware collection check (T2), back-compat flat policy (T1/T4), per-database masking independence (T4), adversarial cross-db denial (T4). Phase 2 (backend `database` param) and Phase 3 (tools/`use_database`/filtered `list_databases`) are explicitly out of scope.

**Placeholders:** none — code provided for every change. Three steps instruct reading an existing method first (`mask_fields_for` body, `evaluate`/`_audit_event`, `AuditLogger.build`) because the surrounding lines must be matched; the new behavior + signatures are fully specified.

**Type consistency:** `DatabaseScope`/`ResolvedScope` fields consistent T1↔T2↔T3. `scope_for(database)` and `database_permitted(database)` signatures consistent across engine (T2) and pipeline (T3). `Request.database`, `evaluate(..., database=)`, `_audit_event(..., database=)`, `PolicyEngine.evaluate(..., database=)`, `AuditLogger.build(..., database=)` all use the same `database: str | None = None` shape. `ErrorCode.DATABASE_NOT_ALLOWED` defined in T2, used in T3.
