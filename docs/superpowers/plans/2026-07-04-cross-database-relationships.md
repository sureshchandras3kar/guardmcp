# Cross-Database Relationships (v1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Discover join keys that link collections ACROSS different databases (shared identifier-name confirmed by value-overlap sampling) and surface them via `guardmcp_relationships` as an additive `cross_db_edges` section — so an AI client can chain governed multi-database queries without guessing join keys.

**Architecture:** A pure matcher + a `CrossDatabaseResolver` (core, database-agnostic) consume per-database non-masked field inventories (via the governed database-scoped `describe_collection`) and a bounded value sampler (new `DatabasePlugin.sample_field_values`, MongoDB-implemented, masked-safe). The existing single-DB relationship path is unchanged; `guardmcp_relationships` gains an additive `cross_db_edges` list.

**Tech Stack:** Python 3.12+, Pydantic v2, motor, pytest/pytest-asyncio.

## Global Constraints

- Deterministic, NO AI/LLM, data-agnostic: NO hardcoded collection/field/product names; candidates are identifier-shaped field names (`_id`, `*_id`, `*Id`) shared across ≥2 databases, confirmed by value overlap. Enum/id values come from live bounded samples, never fixed lists.
- Governance: span only databases in the agent's `databases_allow`; only NON-masked fields participate (masked fields — surfaced by `describe_collection` as type `"masked"` — are excluded from the inventory AND never value-sampled); drop any edge whose endpoint is a denied database/collection or a masked field.
- No new database reads beyond bounded value sampling of already-pruned candidate fields (name-match first, sample second). Sampled value sets are bounded (cap) + cached.
- Backward compatible: single-DB / no `databases_allow` → `cross_db_edges` empty; existing `guardmcp_relationships` output unchanged otherwise. `DatabasePlugin.sample_field_values` default `[]` (other plugins unaffected). All additive.
- Run tests: `/Users/suresh/guardmcp/.venv/bin/python -m pytest <path> -v`. FULL regression each task: `/Users/suresh/guardmcp/.venv/bin/python -m pytest -q --deselect tests/integration/test_transport_lifecycle.py::test_streamable_http_db_tool_survives_session_boundary`. Eval: `/Users/suresh/guardmcp/.venv/bin/python -m guardmcp.eval evals/cases/` (42/42). Lint: `/Users/suresh/guardmcp/.venv/bin/python -m ruff check src tests`. (No `python` on PATH.) Run `git status` at each gate — confirm clean (no uncommitted edit masking a committed failure).
- Codebase-orientation rule (repo mandate): before reading a source file to understand it, run `graphify query "<question>"`; if graphify is unavailable in the shell, read the file directly. Applies to subagents.
- Commit bodies end with: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

## Constants (fixed, documented)

- `_ID_NAME_RE = re.compile(r"(^_id$|_id$|Id$)")` — identifier-shaped field names (candidate join keys).
- `OVERLAP_MIN = 0.3` — `overlap_ratio` at/above this upgrades a candidate to `value_overlap`.
- `SAMPLE_CAP = 100` — max distinct values sampled per field for overlap.

---

### Task 1: Cross-DB models (`core/planning/models.py`)

**Files:**
- Modify: `src/guardmcp/core/planning/models.py`
- Test: `tests/unit/test_cross_db_models.py`

**Interfaces:**
- Produces:
  - `CrossDbEndpoint(database: str, collection: str, field: str)`
  - `CrossDbEdge(from_: CrossDbEndpoint, to: CrossDbEndpoint, kind: str, confidence: float, overlap_ratio: float | None = None, evidence: str = "")` — use a Pydantic alias so the field is written `from_` in Python but serialized as `"from"` (JSON), since `from` is a reserved word.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_cross_db_models.py
from guardmcp.core.planning.models import CrossDbEdge, CrossDbEndpoint


def test_endpoint_fields():
    e = CrossDbEndpoint(database="identity", collection="user", field="account_id")
    assert (e.database, e.collection, e.field) == ("identity", "user", "account_id")


def test_edge_defaults_and_from_alias():
    edge = CrossDbEdge(
        from_=CrossDbEndpoint(database="identity", collection="user", field="account_id"),
        to=CrossDbEndpoint(database="inventory", collection="resource", field="account_id"),
        kind="shared_name", confidence=0.5,
    )
    assert edge.overlap_ratio is None and edge.evidence == ""
    dumped = edge.model_dump(by_alias=True)
    assert "from" in dumped and dumped["from"]["database"] == "identity"
    assert dumped["to"]["field"] == "account_id"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest tests/unit/test_cross_db_models.py -v`
Expected: FAIL — `ImportError: cannot import name 'CrossDbEdge'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/guardmcp/core/planning/models.py` (uses the existing `BaseModel`, `Field` imports):

```python
class CrossDbEndpoint(BaseModel):
    database: str
    collection: str
    field: str


class CrossDbEdge(BaseModel):
    model_config = {"populate_by_name": True}
    from_: CrossDbEndpoint = Field(alias="from")
    to: CrossDbEndpoint
    kind: str  # "shared_name" | "value_overlap"
    confidence: float
    overlap_ratio: float | None = None
    evidence: str = ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest tests/unit/test_cross_db_models.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/guardmcp/core/planning/models.py tests/unit/test_cross_db_models.py
git commit -m "feat(context): cross-database relationship models"
```

---

### Task 2: Cross-DB matcher (`core/planning/cross_db.py`)

**Files:**
- Create: `src/guardmcp/core/planning/cross_db.py`
- Test: `tests/unit/test_cross_db_matcher.py`

**Interfaces:**
- Consumes: `CrossDbEndpoint`, `CrossDbEdge` (Task 1).
- Produces:
  - `def cross_db_candidates(inventory: dict[tuple[str, str], set[str]]) -> list[tuple[str, tuple[str,str], tuple[str,str]]]` — given `{(database, collection): {field_names}}`, return, for each identifier-shaped field name present in ≥2 collections that live in ≥2 DIFFERENT databases, the pairwise `(field, (dbA, collA), (dbB, collB))` candidates (dbA != dbB).
  - `async def match_cross_db(inventory, sample_values) -> list[CrossDbEdge]` where `sample_values(database, collection, field) -> list` is an async callable returning bounded distinct values. For each candidate: build a `shared_name` edge (confidence 0.5); sample both sides; compute `overlap_ratio = |A∩B| / min(|A|,|B|)` (0 if either side empty); if `>= OVERLAP_MIN` → `kind="value_overlap"`, `confidence = round(min(0.9, 0.5 + 0.4*ratio), 4)`, set `overlap_ratio`; else keep `shared_name` at 0.5 with `overlap_ratio=ratio`. Deterministic ordering (sort candidates by `(field, dbA, collA, dbB, collB)`).
  - Module constants `_ID_NAME_RE`, `OVERLAP_MIN = 0.3`, `SAMPLE_CAP = 100`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_cross_db_matcher.py
import pytest

from guardmcp.core.planning.cross_db import cross_db_candidates, match_cross_db


def test_candidates_only_id_shaped_shared_across_databases():
    inv = {
        ("identity", "user"): {"_id", "account_id", "name"},
        ("inventory", "resource"): {"_id", "account_id", "status"},
        ("identity", "role"): {"_id", "account_id"},
    }
    cands = cross_db_candidates(inv)
    fields = {c[0] for c in cands}
    # account_id shared across identity+inventory (different dbs) -> candidate;
    # "name"/"status" not id-shaped -> excluded; _id is id-shaped and shared across dbs too.
    assert "account_id" in fields
    assert "name" not in fields and "status" not in fields
    # every candidate spans two DIFFERENT databases
    for _f, (dba, _ca), (dbb, _cb) in cands:
        assert dba != dbb


@pytest.mark.asyncio
async def test_value_overlap_upgrades_confidence():
    inv = {("identity", "user"): {"account_id"}, ("inventory", "resource"): {"account_id"}}
    values = {("identity", "user", "account_id"): ["a", "b", "c"],
              ("inventory", "resource", "account_id"): ["b", "c", "d"]}
    async def sampler(db, coll, field): return values[(db, coll, field)]
    edges = await match_cross_db(inv, sampler)
    e = next(x for x in edges if x.from_.field == "account_id")
    assert e.kind == "value_overlap" and e.confidence > 0.5 and e.overlap_ratio == pytest.approx(2/3)


@pytest.mark.asyncio
async def test_zero_overlap_stays_shared_name():
    inv = {("identity", "user"): {"account_id"}, ("inventory", "resource"): {"account_id"}}
    async def sampler(db, coll, field):
        return ["x", "y"] if db == "identity" else ["p", "q"]
    edges = await match_cross_db(inv, sampler)
    e = edges[0]
    assert e.kind == "shared_name" and e.confidence == 0.5 and e.overlap_ratio == 0.0


@pytest.mark.asyncio
async def test_deterministic():
    inv = {("a", "c1"): {"x_id"}, ("b", "c2"): {"x_id"}}
    async def sampler(db, coll, field): return ["1"]
    r1 = await match_cross_db(inv, sampler)
    r2 = await match_cross_db(inv, sampler)
    assert [e.model_dump(by_alias=True) for e in r1] == [e.model_dump(by_alias=True) for e in r2]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest tests/unit/test_cross_db_matcher.py -v`
Expected: FAIL — `ModuleNotFoundError: ...planning.cross_db`

- [ ] **Step 3: Write minimal implementation**

```python
# src/guardmcp/core/planning/cross_db.py
from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

from .models import CrossDbEdge, CrossDbEndpoint

_ID_NAME_RE = re.compile(r"(^_id$|_id$|Id$)")
OVERLAP_MIN = 0.3
SAMPLE_CAP = 100


def cross_db_candidates(
    inventory: dict[tuple[str, str], set[str]],
) -> list[tuple[str, tuple[str, str], tuple[str, str]]]:
    """Pairwise candidates: an id-shaped field name present in collections that
    live in >=2 different databases. Deterministic order."""
    by_field: dict[str, list[tuple[str, str]]] = {}
    for (db, coll), fields in inventory.items():
        for f in fields:
            if _ID_NAME_RE.search(f):
                by_field.setdefault(f, []).append((db, coll))
    out: list[tuple[str, tuple[str, str], tuple[str, str]]] = []
    for field, locs in by_field.items():
        locs_sorted = sorted(locs)
        for i in range(len(locs_sorted)):
            for j in range(i + 1, len(locs_sorted)):
                a, b = locs_sorted[i], locs_sorted[j]
                if a[0] != b[0]:  # different databases only
                    out.append((field, a, b))
    out.sort(key=lambda c: (c[0], c[1], c[2]))
    return out


async def match_cross_db(
    inventory: dict[tuple[str, str], set[str]],
    sample_values: Callable[[str, str, str], Awaitable[list]],
) -> list[CrossDbEdge]:
    edges: list[CrossDbEdge] = []
    for field, (dba, ca), (dbb, cb) in cross_db_candidates(inventory):
        va = set(await sample_values(dba, ca, field))
        vb = set(await sample_values(dbb, cb, field))
        denom = min(len(va), len(vb))
        ratio = (len(va & vb) / denom) if denom else 0.0
        if ratio >= OVERLAP_MIN:
            kind, conf = "value_overlap", round(min(0.9, 0.5 + 0.4 * ratio), 4)
            ev = f"id-shaped name '{field}' shared across '{dba}' and '{dbb}'; value overlap {ratio:.2f}"
        else:
            kind, conf = "shared_name", 0.5
            ev = f"id-shaped name '{field}' shared across '{dba}' and '{dbb}'; low value overlap"
        edges.append(
            CrossDbEdge(
                **{"from": CrossDbEndpoint(database=dba, collection=ca, field=field)},
                to=CrossDbEndpoint(database=dbb, collection=cb, field=field),
                kind=kind, confidence=conf, overlap_ratio=round(ratio, 4), evidence=ev,
            )
        )
    return edges
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest tests/unit/test_cross_db_matcher.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/guardmcp/core/planning/cross_db.py tests/unit/test_cross_db_matcher.py
git commit -m "feat(context): deterministic cross-database matcher (shared-name + value-overlap)"
```

---

### Task 3: `sample_field_values` seam + MongoDB implementation

**Files:**
- Modify: `src/guardmcp/core/interfaces/plugin.py` (default `sample_field_values`)
- Modify: `src/guardmcp/plugins/mongodb/executor.py` (add `sample_field_values`)
- Modify: `src/guardmcp/plugins/mongodb/plugin.py` (implement `sample_field_values`)
- Test: `tests/unit/test_sample_field_values.py`

**Interfaces:**
- Produces:
  - `DatabasePlugin.sample_field_values(self, collection: str, field: str, database: str | None = None, cap: int = 100) -> list` — default `[]`.
  - `MongoExecutor.sample_field_values(self, collection, field, database=None, cap=100) -> list` — bounded distinct values of one field: `get_collection(collection, database).find({field: {"$ne": None}}, {field: 1, "_id": 0}).limit(cap)`, collect the field's values (deduped), serialized via `_bson_to_json`.
  - `MongoPlugin.sample_field_values(self, collection, field, database=None, cap=100) -> list` — best-effort (try/except → `[]`); delegates to executor.

**Orientation:** run `graphify query "MongoExecutor collection_indexes get_collection _bson_to_json"`; else read `executor.py` for the `get_collection`/`_bson_to_json` pattern and `plugin.py` for the `relationships` method style (mirror its best-effort delegation).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_sample_field_values.py
import pytest


class _Cursor:
    def __init__(self, docs): self._docs = docs
    def limit(self, n): self._docs = self._docs[:n]; return self
    async def to_list(self, n): return self._docs


class _Coll:
    def find(self, filt, proj): return _Cursor([{"account_id": "a"}, {"account_id": "b"}, {"account_id": "a"}])


class _Client:
    def get_collection(self, name, database=None): return _Coll()


@pytest.mark.asyncio
async def test_executor_sample_field_values_distinct():
    from guardmcp.plugins.mongodb.executor import MongoExecutor
    ex = MongoExecutor(_Client())
    vals = await ex.sample_field_values("user", "account_id", database="identity", cap=100)
    assert set(vals) == {"a", "b"}


@pytest.mark.asyncio
async def test_plugin_sample_field_values_delegates_and_guards():
    from guardmcp.plugins.mongodb.plugin import MongoPlugin

    class _Ex:
        async def sample_field_values(self, c, f, database=None, cap=100): return ["x"]
    assert await MongoPlugin(executor=_Ex()).sample_field_values("u", "account_id") == ["x"]

    class _Boom:
        async def sample_field_values(self, *a, **k): raise RuntimeError("x")
    assert await MongoPlugin(executor=_Boom()).sample_field_values("u", "account_id") == []


@pytest.mark.asyncio
async def test_default_plugin_sample_field_values_empty():
    from guardmcp.core.interfaces.plugin import DatabasePlugin

    class _Bare(DatabasePlugin):
        name = "bare"; supported = frozenset()
        async def connect(self, dsn, options): ...
        async def health(self): return True
        async def close(self): ...
        async def execute(self, req): ...
        async def schema(self, resource, sample_size=None): return {}
        async def list_resources(self): return []
        def validate_request(self, req): ...
    assert await _Bare().sample_field_values("u", "f") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest tests/unit/test_sample_field_values.py -v`
Expected: FAIL — `MongoExecutor` has no `sample_field_values`.

- [ ] **Step 3: Write minimal implementation**

Add to `executor.py` (near `collection_indexes`; use the existing `_bson_to_json` import):

```python
    async def sample_field_values(
        self, collection: str, field: str, database: str | None = None, cap: int = 100
    ) -> list:
        col = self._client.get_collection(collection, database)
        cursor = col.find({field: {"$ne": None}}, {field: 1, "_id": 0}).limit(cap)
        docs = await cursor.to_list(cap)
        seen: list = []
        seen_set: set = set()
        for d in docs:
            if field in d:
                v = _bson_to_json(d[field])
                key = str(v)
                if key not in seen_set:
                    seen_set.add(key)
                    seen.append(v)
        return seen
```

Add to `plugin.py` after `relationships` (mirror its best-effort style):

```python
    async def sample_field_values(
        self, collection: str, field: str, database: str | None = None, cap: int = 100
    ) -> list:
        if self._executor is None:
            return []
        try:
            return await self._executor.sample_field_values(collection, field, database, cap)
        except Exception:
            return []
```

Add to `interfaces/plugin.py` after the `relationships` default:

```python
    async def sample_field_values(
        self, collection: str, field: str, database: str | None = None, cap: int = 100
    ) -> list:
        """Bounded distinct sample of one field's values (for cross-DB value
        overlap). Safe default [] so backends without sampling stay valid."""
        return []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest tests/unit/test_sample_field_values.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/guardmcp/core/interfaces/plugin.py src/guardmcp/plugins/mongodb/executor.py src/guardmcp/plugins/mongodb/plugin.py tests/unit/test_sample_field_values.py
git commit -m "feat(context): sample_field_values seam + MongoDB bounded distinct sampler"
```

---

### Task 4: `CrossDatabaseResolver` (governed inventory + matcher wiring)

**Files:**
- Create: `src/guardmcp/core/planning/cross_db_resolver.py`
- Test: `tests/unit/test_cross_db_resolver.py`

**Interfaces:**
- Consumes: `match_cross_db` (Task 2); a `GuardPipeline` exposing `discover_collections(agent, database=)` + `describe_collection(agent, collection, database=)` (Phase 3) and a plugin getter for `sample_field_values` (Task 3); the agent policy's `databases_allow`.
- Produces:
  - `class CrossDatabaseResolver(guard, get_plugin)` with `async def edges(self, agent: str, databases: list[str]) -> list[CrossDbEdge]`:
    1. For each database in `databases`, `cols = await guard.discover_collections(agent, database=db)`; for each col, `desc = await guard.describe_collection(agent, col, database=db)`; inventory `(db, col)` = set of field names whose type is NOT `"masked"` (masked fields excluded). Skip None/empty desc.
    2. `sampler(db, col, field) = await get_plugin().sample_field_values(col, field, database=db, cap=SAMPLE_CAP)` (guarded → []).
    3. `return await match_cross_db(inventory, sampler)`.
  - Best-effort: any per-db/collection failure is skipped; never raises.

**Orientation:** run `graphify query "RelationshipResolver describe_collection discover_collections _active_plugin"`; else read `core/planning/relationships.py` (resolver style) + `server/tools/_common.py` (`_active_plugin`).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_cross_db_resolver.py
import pytest

from guardmcp.core.planning.cross_db_resolver import CrossDatabaseResolver


class _Guard:
    async def discover_collections(self, agent, database=None):
        return {"identity": ["user"], "inventory": ["resource"], "secrets": ["s"]}.get(database, [])
    async def describe_collection(self, agent, collection, database=None):
        return {
            ("identity", "user"): {"fields": {"_id": "objectId", "account_id": "string", "email": "masked"}},
            ("inventory", "resource"): {"fields": {"_id": "objectId", "account_id": "string"}},
        }.get((database, collection))


class _Plugin:
    async def sample_field_values(self, collection, field, database=None, cap=100):
        return {"identity": ["a", "b"], "inventory": ["b", "c"]}[database]


@pytest.mark.asyncio
async def test_resolver_builds_cross_db_edge_on_shared_account_id():
    r = CrossDatabaseResolver(_Guard(), lambda: _Plugin())
    edges = await r.edges("claude", ["identity", "inventory"])
    acc = [e for e in edges if e.from_.field == "account_id"]
    assert acc, "expected an account_id cross-db edge"
    e = acc[0]
    assert {e.from_.database, e.to.database} == {"identity", "inventory"}
    assert e.kind == "value_overlap"  # a,b vs b,c overlap 1/2 >= 0.3


@pytest.mark.asyncio
async def test_masked_field_never_a_cross_db_candidate():
    r = CrossDatabaseResolver(_Guard(), lambda: _Plugin())
    edges = await r.edges("claude", ["identity", "inventory"])
    assert all(e.from_.field != "email" and e.to.field != "email" for e in edges)


@pytest.mark.asyncio
async def test_only_requested_databases_scanned():
    # 'secrets' not in the passed list -> never scanned -> no edge references it
    r = CrossDatabaseResolver(_Guard(), lambda: _Plugin())
    edges = await r.edges("claude", ["identity", "inventory"])
    assert all("secrets" not in (e.from_.database, e.to.database) for e in edges)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest tests/unit/test_cross_db_resolver.py -v`
Expected: FAIL — `ModuleNotFoundError: ...planning.cross_db_resolver`

- [ ] **Step 3: Write minimal implementation**

```python
# src/guardmcp/core/planning/cross_db_resolver.py
from __future__ import annotations

from collections.abc import Callable

from .cross_db import SAMPLE_CAP, match_cross_db
from .models import CrossDbEdge


class CrossDatabaseResolver:
    def __init__(self, guard, get_plugin: Callable[[], object | None]) -> None:
        self._guard = guard
        self._get_plugin = get_plugin

    async def edges(self, agent: str, databases: list[str]) -> list[CrossDbEdge]:
        inventory: dict[tuple[str, str], set[str]] = {}
        for db in databases:
            try:
                cols = await self._guard.discover_collections(agent, database=db)
            except Exception:
                continue
            for col in cols:
                try:
                    desc = await self._guard.describe_collection(agent, col, database=db)
                except Exception:
                    desc = None
                fields = (desc or {}).get("fields", {})
                names = {f for f, t in fields.items() if t != "masked"}
                if names:
                    inventory[(db, col)] = names

        async def sampler(db: str, col: str, field: str) -> list:
            plugin = self._get_plugin()
            if plugin is None:
                return []
            try:
                return await plugin.sample_field_values(col, field, database=db, cap=SAMPLE_CAP)
            except Exception:
                return []

        return await match_cross_db(inventory, sampler)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest tests/unit/test_cross_db_resolver.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/guardmcp/core/planning/cross_db_resolver.py tests/unit/test_cross_db_resolver.py
git commit -m "feat(context): CrossDatabaseResolver (governed inventory + matcher)"
```

---

### Task 5: Extend `guardmcp_relationships` with `cross_db_edges`

**Files:**
- Modify: `src/guardmcp/server/tools/meta/plan_query.py` (`guardmcp_relationships` handler)
- Test: `tests/unit/test_relationships_cross_db_tool.py`

**Interfaces:**
- Consumes: `CrossDatabaseResolver` (Task 4); `_active_plugin` + `_resolve_database`/`ToolContext` (multi-DB Phase 3); the agent policy's `databases_allow`; the existing single-DB `guardmcp_relationships` path.
- Produces: `guardmcp_relationships` output gains `cross_db_edges: [CrossDbEdge(by_alias)]`. Gather the agent's allowed databases: `allowed_dbs = policy.databases_allow` (if empty → cross_db_edges = []). Build the resolver with `get_plugin = lambda: _active_plugin(pipeline)`; `edges = await CrossDatabaseResolver(pipeline, get_plugin).edges(agent, allowed_dbs)`; add `"cross_db_edges": [e.model_dump(by_alias=True) for e in edges]` to the response `data`. Keep the existing within-DB relationships output unchanged.

**Orientation:** run `graphify query "guardmcp_relationships meta plan_query handler planner.relationships"`; else read `meta/plan_query.py` (`guardmcp_relationships`) to see how it builds/returns the graph and how it gets the pipeline/agent. Read how the agent policy is accessed (e.g. `pipeline._policies.get(agent)`).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_relationships_cross_db_tool.py
import json
import pytest
from mcp.server.fastmcp import FastMCP

from guardmcp.core.policy.models import Policy
from guardmcp.server.tools._common import ToolContext
from guardmcp.server.tools.meta import plan_query


class _Plugin:
    name = "mongodb"
    _executor = None
    async def relationships(self, resources): return []
    async def sample_field_values(self, collection, field, database=None, cap=100):
        return {"identity": ["a", "b"], "inventory": ["b", "c"]}.get(database, [])


class _Entry: plugin = _Plugin()
class _Registry:
    def get_active(self): return _Entry()


class _Pipeline:
    _registry = _Registry()
    _policies = None
    async def discover_collections(self, agent, database=None):
        return {"identity": ["user"], "inventory": ["resource"]}.get(database, [])
    async def describe_collection(self, agent, collection, database=None):
        return {("identity","user"): {"fields": {"account_id": "string"}},
                ("inventory","resource"): {"fields": {"account_id": "string"}}}.get((database, collection))


def _register(policy):
    mcp = FastMCP("t")
    pipe = _Pipeline()
    class _L:
        def get(self, a): return policy
    pipe._policies = _L()
    ctx = ToolContext(get_pipeline=lambda: pipe, get_agent=lambda: "claude", get_settings=lambda: None)
    plan_query.register(mcp, ctx)
    return mcp


async def _call(mcp, name, **kw):
    return json.loads(await mcp._tool_manager.get_tool(name).fn(**kw))


@pytest.mark.asyncio
async def test_relationships_includes_cross_db_edges():
    p = Policy(agent="claude", databases_allow=["identity", "inventory"])
    out = await _call(_register(p), "guardmcp_relationships")
    edges = out["data"]["cross_db_edges"]
    assert any(e["from"]["field"] == "account_id" and
               {e["from"]["database"], e["to"]["database"]} == {"identity", "inventory"}
               for e in edges)


@pytest.mark.asyncio
async def test_no_databases_allow_gives_empty_cross_db_edges():
    p = Policy(agent="claude")  # no databases_allow
    out = await _call(_register(p), "guardmcp_relationships")
    assert out["data"]["cross_db_edges"] == []
```

> Confirm the real `guardmcp_relationships` result shape + how it reads the agent policy (mirror `test_plan_query_tool.py` for the FastMCP invocation + envelope). Adapt the fixture to the real handler wiring; keep assertions at full strength.

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest tests/unit/test_relationships_cross_db_tool.py -v`
Expected: FAIL — `KeyError: 'cross_db_edges'`

- [ ] **Step 3: Write minimal implementation**

In `meta/plan_query.py` `guardmcp_relationships` handler: after building the existing single-DB relationships result, read the agent policy (`pipeline._policies.get(agent)`), `allowed_dbs = list(policy.databases_allow) if policy else []`. If `allowed_dbs`: build `resolver = CrossDatabaseResolver(pipeline, lambda: _active_plugin(pipeline))`, `edges = await resolver.edges(agent, allowed_dbs)`, else `edges = []`. Add `"cross_db_edges": [e.model_dump(by_alias=True) for e in edges]` into the response `data` (wrap the whole cross-DB block in try/except → `[]` so it never breaks the existing relationships response). Import `CrossDatabaseResolver` from `....core.planning.cross_db_resolver` and `_active_plugin` from `.._common`.

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest tests/unit/test_relationships_cross_db_tool.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/guardmcp/server/tools/meta/plan_query.py tests/unit/test_relationships_cross_db_tool.py
git commit -m "feat(context): guardmcp_relationships returns cross_db_edges across allowed databases"
```

---

### Task 6: Integration + governance + data-agnostic + back-compat

**Files:**
- Create: `tests/integration/test_cross_db_relationships.py`

**Proves:** (1) end-to-end through `guardmcp_relationships`: two databases sharing an id field with overlapping sampled values → a `value_overlap` cross-DB edge; (2) a masked field never appears as an endpoint; (3) a database NOT in `databases_allow` is never scanned / referenced; (4) product-neutral field names (`grp_id`) matched purely structurally (data-agnostic); (5) back-compat: no `databases_allow` → `cross_db_edges` empty and the existing relationships output unchanged.

- [ ] **Step 1: Write the test**

Write integration tests mirroring the Task 4/5 harnesses (fake `GuardPipeline` + `_Plugin` sampler). Assert: value_overlap edge present with correct endpoints + confidence>0.5; masked field excluded; a denied database name absent from all edges; a `grp_id`-style neutral field matched; empty `databases_allow` → `cross_db_edges == []`. Assert real values (no vacuous asserts).

- [ ] **Step 2: Run it**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest tests/integration/test_cross_db_relationships.py -v`
Expected: PASS. If a real bug surfaces, fix the implicated task (don't weaken the test).

- [ ] **Step 3: Full regression + eval + clean tree**

Run: `git status` (clean). Then `/Users/suresh/guardmcp/.venv/bin/python -m pytest -q --deselect tests/integration/test_transport_lifecycle.py::test_streamable_http_db_tool_survives_session_boundary`. Then `/Users/suresh/guardmcp/.venv/bin/python -m guardmcp.eval evals/cases/` (42/42). Then `/Users/suresh/guardmcp/.venv/bin/python -m ruff check src tests`.
Expected: ALL PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_cross_db_relationships.py
git commit -m "test(context): cross-database relationships integration + governance + data-agnostic"
```

---

## Self-Review

**Spec coverage:** models (T1); matcher shared-name + value-overlap + id-name pruning + determinism (T2); `sample_field_values` seam + Mongo bounded sampler + safe default (T3); governed resolver — allowed-db scope, masked-field exclusion, best-effort (T4); `guardmcp_relationships` additive `cross_db_edges` + empty when no `databases_allow` (T5); integration + governance + data-agnostic + back-compat (T6). Out of scope (identifier-role alignment via field-semantics, transitive path suggestion, auto-join) — not in this plan.

**Placeholders:** none — novel code (models, matcher, sampler, resolver) is complete; T5/T6 give the pattern + a worked fixture and instruct confirming the real `guardmcp_relationships` wiring/envelope (mirror `test_plan_query_tool.py`).

**Type consistency:** `CrossDbEndpoint`/`CrossDbEdge` (with `from_`↔`"from"` alias) consistent T1→T6; `match_cross_db(inventory: dict[(db,coll)->set[field]], sampler)` signature consistent T2↔T4; `sample_field_values(collection, field, database=None, cap=100)` identical across interface/executor/plugin/resolver/tool (T3→T5); resolver `edges(agent, databases) -> list[CrossDbEdge]` consumed by the tool (T5). `OVERLAP_MIN`/`SAMPLE_CAP`/`_ID_NAME_RE` in `cross_db.py` reused by the resolver.
