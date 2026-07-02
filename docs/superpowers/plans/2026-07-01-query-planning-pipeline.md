# Query Planning Pipeline (MongoDB, Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic, no-LLM query-planning pipeline exposed as MCP tool `guardmcp_plan_query` (+ diagnostic `guardmcp_relationships`) that turns a natural-language intent into an ambiguity report, relationship graph, and ranked candidate execution plans — without executing or bypassing governance.

**Architecture:** A new database-agnostic `core/planning/` package of independent stage classes orchestrated by `PlanningPipeline`. Plans wrap the existing `CapabilityRequest` (the portable IR — no new IR). Metadata is read only through governed accessors (`GuardPipeline.discover_collections`/`describe_collection`) plus one new optional `DatabasePlugin.relationships()` method (safe default `[]`, implemented by MongoPlugin only). Per-plan cost via `plugin.estimate()`, per-plan governance via `GuardPipeline.evaluate_capability()`. Nothing calls `executor.execute()`.

**Tech Stack:** Python 3.12, Pydantic v2, pytest / pytest-asyncio, MongoDB (motor). MCP via FastMCP.

## Global Constraints

- No AI/LLM logic anywhere in planning. Deterministic only.
- Planner MUST NOT call `executor.execute()` / run queries. Only `plugin.estimate()` (explain) and `pipeline.evaluate_capability()` (no execution) are permitted side-effect-free calls.
- Planner reads metadata ONLY via `GuardPipeline.discover_collections(agent)`, `GuardPipeline.describe_collection(agent, collection)`, and `DatabasePlugin.relationships(resources)`. Never touch a denied collection or masked field.
- `ExecutionPlan.request` is a `guardmcp.core.interfaces.capability.CapabilityRequest`. Do NOT invent a new IR.
- Do NOT modify or rename the existing `guardmcp_plan` tool (`src/guardmcp/server/tools/meta/plan.py`).
- New plugin method default returns `[]` so Postgres/MySQL/future plugins stay valid unchanged.
- Every planning entry point degrades gracefully (append to `notes[]`), never raises out of a stage.
- Run tests with: `python -m pytest <path> -v`. Lint: `ruff check src tests`.

---

### Task 1: Planning models (`core/planning/models.py`)

**Files:**
- Create: `src/guardmcp/core/planning/__init__.py`
- Create: `src/guardmcp/core/planning/models.py`
- Test: `tests/unit/test_planning_models.py`

**Interfaces:**
- Consumes: `guardmcp.core.interfaces.capability.CapabilityRequest`, `guardmcp.core.interfaces.cost.CostEstimate`.
- Produces (imported by all later tasks):
  - `Relationship(from_resource, from_field, to_resource, to_field, kind, confidence, evidence)`
  - `RelationshipGraph(nodes: list[str], edges: list[Relationship], generated_at: str, cached: bool=False)`
  - `Interpretation(field: str, operator: str, value, confidence: float, evidence: str)`
  - `AmbiguityReport(ambiguous: bool, confidence: float, interpretations: list[Interpretation], recommendation: str)`
  - `ExecutionPlan(strategy: str, request: CapabilityRequest, relationships_used: list[Relationship]=[], est_cost: CostEstimate|None=None, complexity: str="unknown", index_used: bool|None=None, risk_level: str|None=None, governance: dict={}, limitations: list[str]=[])`
  - `AlternativePlan(ExecutionPlan) + rank: int, tradeoff: str`
  - `PlanningContext(agent: str, intent: str, resource: str|None, allowed_resources: list[str], resource_schema: dict, indexes: list[dict], relationships: RelationshipGraph)` — field named `resource_schema` (NOT `schema`, which shadows `pydantic.BaseModel` and emits a UserWarning)
  - `PlannerResult(ambiguity: AmbiguityReport, relationships: RelationshipGraph, plans: list[AlternativePlan]=[], recommended_plan: AlternativePlan|None=None, notes: list[str]=[])`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_planning_models.py
from guardmcp.core.interfaces.capability import Capability, CapabilityRequest
from guardmcp.core.planning.models import (
    AlternativePlan,
    AmbiguityReport,
    ExecutionPlan,
    Interpretation,
    PlannerResult,
    PlanningContext,
    Relationship,
    RelationshipGraph,
)


def test_relationship_graph_defaults():
    g = RelationshipGraph(nodes=["user", "project"], edges=[], generated_at="t")
    assert g.cached is False
    assert g.edges == []


def test_execution_plan_wraps_capability_request():
    req = CapabilityRequest(capability=Capability.READ, resource="user", filter={"status": "ACTIVE"})
    plan = ExecutionPlan(strategy="index_scan", request=req)
    assert plan.request.resource == "user"
    assert plan.complexity == "unknown"
    assert plan.limitations == []


def test_alternative_plan_extends_execution_plan():
    req = CapabilityRequest(capability=Capability.READ, resource="user")
    alt = AlternativePlan(strategy="collscan", request=req, rank=1, tradeoff="no index")
    assert isinstance(alt, ExecutionPlan)
    assert alt.rank == 1


def test_planner_result_defaults():
    amb = AmbiguityReport(ambiguous=False, confidence=1.0, interpretations=[], recommendation="")
    g = RelationshipGraph(nodes=[], edges=[], generated_at="t")
    res = PlannerResult(ambiguity=amb, relationships=g)
    assert res.plans == []
    assert res.recommended_plan is None
    assert res.notes == []


def test_planning_context_holds_authorized_only():
    g = RelationshipGraph(nodes=[], edges=[], generated_at="t")
    ctx = PlanningContext(
        agent="claude", intent="show active users", resource="user",
        allowed_resources=["user"], resource_schema={"fields": {}}, indexes=[], relationships=g,
    )
    assert ctx.allowed_resources == ["user"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_planning_models.py -v`
Expected: FAIL — `ModuleNotFoundError: guardmcp.core.planning`

- [ ] **Step 3: Write minimal implementation**

```python
# src/guardmcp/core/planning/__init__.py
"""Deterministic, no-LLM query planning pipeline (database-agnostic)."""
```

```python
# src/guardmcp/core/planning/models.py
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from ..interfaces.capability import CapabilityRequest
from ..interfaces.cost import CostEstimate

RelationshipKind = Literal["fk", "index", "naming", "sampled"]


class Relationship(BaseModel):
    from_resource: str
    from_field: str
    to_resource: str
    to_field: str
    kind: RelationshipKind
    confidence: float
    evidence: str


class RelationshipGraph(BaseModel):
    nodes: list[str] = Field(default_factory=list)
    edges: list[Relationship] = Field(default_factory=list)
    generated_at: str
    cached: bool = False


class Interpretation(BaseModel):
    field: str
    operator: str
    value: Any = None
    confidence: float
    evidence: str


class AmbiguityReport(BaseModel):
    ambiguous: bool
    confidence: float
    interpretations: list[Interpretation] = Field(default_factory=list)
    recommendation: str = ""


class ExecutionPlan(BaseModel):
    strategy: str
    request: CapabilityRequest
    relationships_used: list[Relationship] = Field(default_factory=list)
    est_cost: CostEstimate | None = None
    complexity: str = "unknown"
    index_used: bool | None = None
    risk_level: str | None = None
    governance: dict[str, Any] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)


class AlternativePlan(ExecutionPlan):
    rank: int = 0
    tradeoff: str = ""


class PlanningContext(BaseModel):
    agent: str
    intent: str
    resource: str | None = None
    allowed_resources: list[str] = Field(default_factory=list)
    resource_schema: dict[str, Any] = Field(default_factory=dict)
    indexes: list[dict[str, Any]] = Field(default_factory=list)
    relationships: RelationshipGraph


class PlannerResult(BaseModel):
    ambiguity: AmbiguityReport
    relationships: RelationshipGraph
    plans: list[AlternativePlan] = Field(default_factory=list)
    recommended_plan: AlternativePlan | None = None
    notes: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_planning_models.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/guardmcp/core/planning/__init__.py src/guardmcp/core/planning/models.py tests/unit/test_planning_models.py
git commit -m "feat(planning): typed planning models wrapping CapabilityRequest"
```

---

### Task 2: Plugin `relationships()` seam + MongoPlugin implementation

**Files:**
- Modify: `src/guardmcp/core/interfaces/plugin.py` (add default method after `cross_resource_refs`, ~line 68)
- Create: `src/guardmcp/plugins/mongodb/relationships.py`
- Modify: `src/guardmcp/plugins/mongodb/plugin.py` (add `relationships` method after `list_resources`, ~line 196)
- Test: `tests/unit/test_mongo_relationships.py`

**Interfaces:**
- Consumes: `MongoExecutor.collection_indexes(collection) -> list[dict]` (each `{"name","key":[(field,dir)...],"unique","sparse","type"}`), `MongoExecutor.collection_schema(collection, mask_fields, sample_size) -> {"<field>": "<type>", ...}` OR `{}`.
- Produces:
  - `DatabasePlugin.relationships(self, resources: list[str]) -> list[dict]` (default `[]`).
  - `MongoPlugin.relationships(self, resources)` → concrete impl.
  - `infer_relationships(resources, schemas, indexes_by_resource) -> list[dict]` pure function in `relationships.py`. Each dict has keys: `from_resource, from_field, to_resource, to_field, kind, confidence, evidence`.

**Algorithm (deterministic, naming + index based):**
For each resource R and each field F in R's schema: if F matches `<name>_id` or `<name>Id` (case-insensitive, F != `_id`), derive candidate target `name`. Match target if any resource T (T != R) equals `name`, `name+"s"`, or `name` == singular(T) (strip trailing `s`). Emit edge R.F -> T._id. `kind="index"` and `confidence=0.75` if F is a key in any of R's indexes, else `kind="naming"` and `confidence=0.5`. `evidence` describes the rule. Sort edges by `(from_resource, from_field, to_resource)` for determinism.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_mongo_relationships.py
import pytest

from guardmcp.plugins.mongodb.relationships import infer_relationships


def test_naming_convention_edge():
    schemas = {"user": {"_id": "objectId", "name": "string"},
               "project": {"_id": "objectId", "user_id": "objectId"}}
    edges = infer_relationships(["user", "project"], schemas, {"user": [], "project": []})
    assert len(edges) == 1
    e = edges[0]
    assert (e["from_resource"], e["from_field"], e["to_resource"], e["to_field"]) == (
        "project", "user_id", "user", "_id")
    assert e["kind"] == "naming"
    assert e["confidence"] == 0.5


def test_indexed_fk_field_higher_confidence():
    schemas = {"user": {"_id": "objectId"},
               "project": {"_id": "objectId", "user_id": "objectId"}}
    indexes = {"user": [], "project": [{"name": "user_id_1", "key": [("user_id", 1)]}]}
    edges = infer_relationships(["user", "project"], schemas, indexes)
    assert edges[0]["kind"] == "index"
    assert edges[0]["confidence"] == 0.75


def test_no_edge_when_target_not_allowed():
    schemas = {"project": {"_id": "objectId", "user_id": "objectId"}}
    edges = infer_relationships(["project"], schemas, {"project": []})
    assert edges == []


class _FakeExecutor:
    async def collection_schema(self, collection, mask_fields, sample_size=None):
        return {"user": {"_id": "objectId"},
                "project": {"_id": "objectId", "user_id": "objectId"}}[collection]

    async def collection_indexes(self, collection):
        return []


@pytest.mark.asyncio
async def test_mongo_plugin_relationships_uses_executor():
    from guardmcp.plugins.mongodb.plugin import MongoPlugin
    plugin = MongoPlugin(executor=_FakeExecutor())
    edges = await plugin.relationships(["user", "project"])
    assert edges[0]["from_resource"] == "project"


@pytest.mark.asyncio
async def test_default_plugin_relationships_empty():
    from guardmcp.core.interfaces.plugin import DatabasePlugin

    class _Bare(DatabasePlugin):
        name = "bare"
        supported = frozenset()
        async def connect(self, dsn, options): ...
        async def health(self): return True
        async def close(self): ...
        async def execute(self, req): ...
        async def schema(self, resource, sample_size=None): return {}
        async def list_resources(self): return []
        def validate_request(self, req): ...

    assert await _Bare().relationships(["a", "b"]) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_mongo_relationships.py -v`
Expected: FAIL — `ModuleNotFoundError: ...mongodb.relationships`

- [ ] **Step 3: Write minimal implementation**

```python
# src/guardmcp/plugins/mongodb/relationships.py
"""Deterministic relationship inference from field names + indexes (Mongo)."""
from __future__ import annotations

import re

_FK_RE = re.compile(r"^(?P<name>.+?)_id$|^(?P<name2>.+?)Id$")


def _target_of(field: str) -> str | None:
    if field == "_id":
        return None
    m = _FK_RE.match(field)
    if not m:
        return None
    return m.group("name") or m.group("name2")


def _matches_resource(target: str, resource: str) -> bool:
    t = target.lower()
    r = resource.lower()
    return r == t or r == t + "s" or (r.endswith("s") and r[:-1] == t)


def _indexed_fields(indexes: list[dict]) -> set[str]:
    fields: set[str] = set()
    for idx in indexes:
        for pair in idx.get("key", []):
            # key entries are (field, direction) tuples
            fields.add(pair[0] if isinstance(pair, (list, tuple)) else pair)
    return fields


def infer_relationships(
    resources: list[str],
    schemas: dict[str, dict],
    indexes_by_resource: dict[str, list[dict]],
) -> list[dict]:
    edges: list[dict] = []
    resource_set = set(resources)
    for r in resources:
        fields = schemas.get(r, {})
        indexed = _indexed_fields(indexes_by_resource.get(r, []))
        for field in fields:
            target = _target_of(field)
            if target is None:
                continue
            for t in resource_set:
                if t == r or not _matches_resource(target, t):
                    continue
                is_indexed = field in indexed
                edges.append(
                    {
                        "from_resource": r,
                        "from_field": field,
                        "to_resource": t,
                        "to_field": "_id",
                        "kind": "index" if is_indexed else "naming",
                        "confidence": 0.75 if is_indexed else 0.5,
                        "evidence": (
                            f"field '{field}' on '{r}' "
                            + ("is indexed and " if is_indexed else "")
                            + f"matches resource '{t}' by naming convention"
                        ),
                    }
                )
    edges.sort(key=lambda e: (e["from_resource"], e["from_field"], e["to_resource"]))
    return edges
```

Add to `src/guardmcp/core/interfaces/plugin.py` immediately after the `cross_resource_refs` method (~line 68):

```python
    async def relationships(self, resources: list[str]) -> list[dict]:
        """Return normalized relationship hints among `resources`.

        Each dict: {from_resource, from_field, to_resource, to_field, kind,
        confidence, evidence}. Safe default `[]` so backends that cannot infer
        relationships (and all not-yet-updated plugins) stay valid unchanged.
        """
        return []
```

Add to `src/guardmcp/plugins/mongodb/plugin.py` after `list_resources` (~line 196):

```python
    async def relationships(self, resources: list[str]) -> list[dict]:
        """Infer relationships among `resources` from field names + indexes.
        Best-effort: any per-resource introspection failure is skipped, never
        raised, so planning degrades gracefully."""
        from .relationships import infer_relationships

        if self._executor is None:
            return []
        schemas: dict[str, dict] = {}
        indexes: dict[str, list[dict]] = {}
        for r in resources:
            try:
                schemas[r] = await self._executor.collection_schema(r, [], None)
            except Exception:
                schemas[r] = {}
            try:
                indexes[r] = await self._executor.collection_indexes(r)
            except Exception:
                indexes[r] = []
        return infer_relationships(resources, schemas, indexes)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_mongo_relationships.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/guardmcp/core/interfaces/plugin.py src/guardmcp/plugins/mongodb/relationships.py src/guardmcp/plugins/mongodb/plugin.py tests/unit/test_mongo_relationships.py
git commit -m "feat(planning): DatabasePlugin.relationships seam + MongoPlugin impl"
```

---

### Task 3: RelationshipResolver with cache (`core/planning/relationships.py`)

**Files:**
- Create: `src/guardmcp/core/planning/relationships.py`
- Test: `tests/unit/test_relationship_resolver.py`

**Interfaces:**
- Consumes: `Relationship`, `RelationshipGraph` (Task 1); a `get_plugin: Callable[[], DatabasePlugin | None]`.
- Produces:
  - `class RelationshipResolver`
    - `__init__(self, get_plugin, *, ttl_seconds: int = 300, clock=time.monotonic)`
    - `async def graph(self, allowed_resources: list[str], *, force: bool = False) -> RelationshipGraph`
    - `def invalidate(self) -> None`

**Rules:** cache key = `tuple(sorted(allowed_resources))`. On hit within TTL and not `force`, return graph with `cached=True`. Security filter: drop any edge whose `from_resource` or `to_resource` is not in `allowed_resources`. If plugin is None or `relationships()` raises, return an empty graph (nodes only). `generated_at` = ISO-8601 UTC.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_relationship_resolver.py
import pytest

from guardmcp.core.planning.relationships import RelationshipResolver


class _Plugin:
    def __init__(self, edges):
        self._edges = edges
        self.calls = 0

    async def relationships(self, resources):
        self.calls += 1
        return self._edges


@pytest.mark.asyncio
async def test_graph_builds_nodes_and_edges():
    edges = [{"from_resource": "project", "from_field": "user_id", "to_resource": "user",
              "to_field": "_id", "kind": "naming", "confidence": 0.5, "evidence": "x"}]
    r = RelationshipResolver(lambda: _Plugin(edges))
    g = await r.graph(["user", "project"])
    assert set(g.nodes) == {"user", "project"}
    assert len(g.edges) == 1
    assert g.cached is False


@pytest.mark.asyncio
async def test_graph_filters_edges_to_allowed():
    edges = [{"from_resource": "project", "from_field": "secret_id", "to_resource": "secrets",
              "to_field": "_id", "kind": "naming", "confidence": 0.5, "evidence": "x"}]
    r = RelationshipResolver(lambda: _Plugin(edges))
    g = await r.graph(["project"])  # 'secrets' not allowed
    assert g.edges == []


@pytest.mark.asyncio
async def test_cache_hit_marks_cached_and_skips_plugin():
    plugin = _Plugin([])
    r = RelationshipResolver(lambda: plugin)
    await r.graph(["user"])
    g2 = await r.graph(["user"])
    assert g2.cached is True
    assert plugin.calls == 1


@pytest.mark.asyncio
async def test_force_and_invalidate_refetch():
    plugin = _Plugin([])
    r = RelationshipResolver(lambda: plugin)
    await r.graph(["user"])
    await r.graph(["user"], force=True)
    assert plugin.calls == 2
    r.invalidate()
    await r.graph(["user"])
    assert plugin.calls == 3


@pytest.mark.asyncio
async def test_no_plugin_returns_empty_graph():
    r = RelationshipResolver(lambda: None)
    g = await r.graph(["user"])
    assert g.edges == []
    assert g.nodes == ["user"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_relationship_resolver.py -v`
Expected: FAIL — `ModuleNotFoundError: ...planning.relationships`

- [ ] **Step 3: Write minimal implementation**

```python
# src/guardmcp/core/planning/relationships.py
from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime

from .models import Relationship, RelationshipGraph


class RelationshipResolver:
    def __init__(self, get_plugin: Callable[[], object | None], *, ttl_seconds: int = 300,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._get_plugin = get_plugin
        self._ttl = ttl_seconds
        self._clock = clock
        self._cache: dict[tuple[str, ...], tuple[float, RelationshipGraph]] = {}

    def invalidate(self) -> None:
        self._cache.clear()

    async def graph(self, allowed_resources: list[str], *, force: bool = False) -> RelationshipGraph:
        key = tuple(sorted(allowed_resources))
        now = self._clock()
        if not force and key in self._cache:
            ts, cached = self._cache[key]
            if now - ts < self._ttl:
                return cached.model_copy(update={"cached": True})

        allowed = set(allowed_resources)
        edges: list[Relationship] = []
        plugin = self._get_plugin()
        if plugin is not None:
            try:
                raw = await plugin.relationships(list(allowed_resources))
            except Exception:
                raw = []
            for e in raw:
                if e.get("from_resource") in allowed and e.get("to_resource") in allowed:
                    edges.append(Relationship(**e))
        graph = RelationshipGraph(
            nodes=list(allowed_resources),
            edges=edges,
            generated_at=datetime.now(UTC).isoformat(),
            cached=False,
        )
        self._cache[key] = (now, graph)
        return graph
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_relationship_resolver.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/guardmcp/core/planning/relationships.py tests/unit/test_relationship_resolver.py
git commit -m "feat(planning): RelationshipResolver with TTL cache + security filter"
```

---

### Task 4: AmbiguityDetector (`core/planning/ambiguity.py`)

**Files:**
- Create: `src/guardmcp/core/planning/ambiguity.py`
- Test: `tests/unit/test_ambiguity_detector.py`

**Interfaces:**
- Consumes: `AmbiguityReport`, `Interpretation`, `PlanningContext` (Task 1).
- Produces:
  - `class AmbiguityDetector` with `def detect(self, intent: str, schema_fields: dict[str, str], indexed_fields: set[str]) -> AmbiguityReport`.

**Algorithm (deterministic):** Lowercase-tokenize `intent`. For each concept keyword present, gather its candidate `(field, operator, value)` templates from `_CONCEPTS`. Keep only candidates whose `field` exists in `schema_fields`. Per surviving candidate: `confidence = 0.5 + (0.1 if field in indexed_fields else 0.0)`. Sort by `(-confidence, field)`. `ambiguous = len(survivors) >= 2`. Report `confidence` = top candidate confidence (or 1.0 if 0/1 survivor). `recommendation` = "Ask user for clarification." when ambiguous, else "" . Deterministic ordering guarantees stable output.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_ambiguity_detector.py
from guardmcp.core.planning.ambiguity import AmbiguityDetector


def test_two_active_candidates_is_ambiguous():
    d = AmbiguityDetector()
    schema = {"status": "string", "is_active": "bool"}
    r = d.detect("show active users", schema, indexed_fields=set())
    assert r.ambiguous is True
    assert len(r.interpretations) >= 2
    assert "clarif" in r.recommendation.lower()


def test_single_candidate_not_ambiguous():
    d = AmbiguityDetector()
    schema = {"status": "string"}
    r = d.detect("show active users", schema, indexed_fields=set())
    assert r.ambiguous is False
    assert len(r.interpretations) == 1
    assert r.interpretations[0].field == "status"


def test_no_candidate_not_ambiguous():
    d = AmbiguityDetector()
    r = d.detect("list projects", {"name": "string"}, indexed_fields=set())
    assert r.ambiguous is False
    assert r.interpretations == []


def test_indexed_candidate_ranks_first():
    d = AmbiguityDetector()
    schema = {"status": "string", "is_active": "bool"}
    r = d.detect("active", schema, indexed_fields={"is_active"})
    assert r.interpretations[0].field == "is_active"
    assert r.interpretations[0].confidence == 0.6


def test_deterministic_output():
    d = AmbiguityDetector()
    schema = {"status": "string", "is_active": "bool", "enabled": "bool"}
    a = d.detect("active", schema, set())
    b = d.detect("active", schema, set())
    assert a.model_dump() == b.model_dump()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_ambiguity_detector.py -v`
Expected: FAIL — `ModuleNotFoundError: ...planning.ambiguity`

- [ ] **Step 3: Write minimal implementation**

```python
# src/guardmcp/core/planning/ambiguity.py
from __future__ import annotations

import re
from typing import Any

from .models import AmbiguityReport, Interpretation

# concept keyword -> candidate (field, operator, value) templates.
# Detection keeps only templates whose field exists in the collection schema.
_CONCEPTS: dict[str, list[tuple[str, str, Any]]] = {
    "active": [
        ("status", "=", "ACTIVE"),
        ("state", "=", "ACTIVE"),
        ("is_active", "=", True),
        ("active", "=", True),
        ("enabled", "=", True),
        ("account_enabled", "=", True),
    ],
    "inactive": [
        ("status", "=", "INACTIVE"),
        ("is_active", "=", False),
        ("enabled", "=", False),
        ("account_enabled", "=", False),
    ],
    "enabled": [("enabled", "=", True), ("account_enabled", "=", True), ("is_active", "=", True)],
    "disabled": [("enabled", "=", False), ("account_enabled", "=", False)],
}

_TOKEN_RE = re.compile(r"[a-z_]+")


class AmbiguityDetector:
    def detect(
        self, intent: str, schema_fields: dict[str, str], indexed_fields: set[str]
    ) -> AmbiguityReport:
        tokens = set(_TOKEN_RE.findall(intent.lower()))
        seen: set[tuple[str, str]] = set()
        survivors: list[Interpretation] = []
        for concept, templates in _CONCEPTS.items():
            if concept not in tokens:
                continue
            for field, op, value in templates:
                if field not in schema_fields:
                    continue
                dedup = (field, str(value))
                if dedup in seen:
                    continue
                seen.add(dedup)
                confidence = 0.5 + (0.1 if field in indexed_fields else 0.0)
                survivors.append(
                    Interpretation(
                        field=field,
                        operator=op,
                        value=value,
                        confidence=confidence,
                        evidence=f"concept '{concept}' maps to field '{field}' present in schema",
                    )
                )
        survivors.sort(key=lambda i: (-i.confidence, i.field))
        ambiguous = len(survivors) >= 2
        top = survivors[0].confidence if survivors else 1.0
        return AmbiguityReport(
            ambiguous=ambiguous,
            confidence=top if ambiguous else 1.0,
            interpretations=survivors,
            recommendation="Ask user for clarification." if ambiguous else "",
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_ambiguity_detector.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/guardmcp/core/planning/ambiguity.py tests/unit/test_ambiguity_detector.py
git commit -m "feat(planning): deterministic AmbiguityDetector over schema metadata"
```

---

### Task 5: QueryPlanner + AlternativePlanner (`core/planning/planner.py`)

**Files:**
- Create: `src/guardmcp/core/planning/planner.py`
- Test: `tests/unit/test_query_planner.py`

**Interfaces:**
- Consumes: `Capability`, `CapabilityRequest` (interfaces.capability); `ExecutionPlan`, `AlternativePlan`, `PlanningContext`, `Interpretation` (Task 1).
- Produces:
  - `def indexed_fields(indexes: list[dict]) -> set[str]` (shared helper).
  - `class QueryPlanner` with `def build(self, context: PlanningContext, interpretation: Interpretation | None) -> ExecutionPlan`.
  - `class AlternativePlanner` with `def expand(self, base: ExecutionPlan, context: PlanningContext) -> list[ExecutionPlan]`.

**Rules — QueryPlanner.build:** build a READ `CapabilityRequest(capability=READ, resource=context.resource, filter=<from interpretation or None>, sort=<from intent>, limit=<from intent>)`. Detect `sort`: if intent contains "top"/"highest"/"most" AND a numeric-looking field token exists in schema, sort that field `-1`; else no sort. Detect `limit`: parse first integer in intent (e.g. "top 10" → 10), else None. `index_used` = True if the filter field is in `indexed_fields(context.indexes)` (None when no filter). `strategy="index_scan"` if `index_used` else `"collection_scan"`. `complexity="low"` if index_used else `"high"`.

**Rules — AlternativePlanner.expand:** always include `base`. If `base.request.filter` is truthy, add an aggregation alternative: same predicate expressed as `pipeline=[{"$match": filter}, {"$limit": limit or 50}]`, `capability=AGGREGATE`, `strategy="aggregation"`, `tradeoff="pipeline form; enables downstream $group/$lookup"`. Never produce duplicate strategies.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_query_planner.py
from guardmcp.core.interfaces.capability import Capability
from guardmcp.core.planning.models import (
    Interpretation, PlanningContext, RelationshipGraph,
)
from guardmcp.core.planning.planner import (
    AlternativePlanner, QueryPlanner, indexed_fields,
)


def _ctx(resource="user", intent="show active users", indexes=None, schema=None):
    return PlanningContext(
        agent="claude", intent=intent, resource=resource,
        allowed_resources=[resource],
        resource_schema={"fields": schema or {"status": "string", "revenue": "double"}},
        indexes=indexes or [],
        relationships=RelationshipGraph(nodes=[resource], edges=[], generated_at="t"),
    )


def test_indexed_fields_helper():
    idx = [{"name": "status_1", "key": [("status", 1)]}]
    assert indexed_fields(idx) == {"status"}


def test_build_read_plan_with_filter():
    interp = Interpretation(field="status", operator="=", value="ACTIVE", confidence=0.6, evidence="x")
    plan = QueryPlanner().build(_ctx(), interp)
    assert plan.request.capability == Capability.READ
    assert plan.request.filter == {"status": "ACTIVE"}
    assert plan.strategy == "collection_scan"
    assert plan.index_used is False


def test_build_marks_index_used():
    interp = Interpretation(field="status", operator="=", value="ACTIVE", confidence=0.6, evidence="x")
    ctx = _ctx(indexes=[{"name": "status_1", "key": [("status", 1)]}])
    plan = QueryPlanner().build(ctx, interp)
    assert plan.index_used is True
    assert plan.strategy == "index_scan"
    assert plan.complexity == "low"


def test_build_parses_top_n_sort_and_limit():
    ctx = _ctx(intent="top 10 users by revenue")
    plan = QueryPlanner().build(ctx, None)
    assert plan.request.limit == 10
    assert plan.request.sort == {"revenue": -1}


def test_alternative_planner_adds_aggregation():
    interp = Interpretation(field="status", operator="=", value="ACTIVE", confidence=0.6, evidence="x")
    base = QueryPlanner().build(_ctx(), interp)
    alts = AlternativePlanner().expand(base, _ctx())
    strategies = {a.strategy for a in alts}
    assert "aggregation" in strategies
    agg = next(a for a in alts if a.strategy == "aggregation")
    assert agg.request.pipeline[0] == {"$match": {"status": "ACTIVE"}}


def test_alternative_planner_no_agg_without_filter():
    base = QueryPlanner().build(_ctx(intent="list users"), None)
    alts = AlternativePlanner().expand(base, _ctx(intent="list users"))
    assert all(a.strategy != "aggregation" for a in alts)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_query_planner.py -v`
Expected: FAIL — `ModuleNotFoundError: ...planning.planner`

- [ ] **Step 3: Write minimal implementation**

```python
# src/guardmcp/core/planning/planner.py
from __future__ import annotations

import re

from ..interfaces.capability import Capability, CapabilityRequest
from .models import AlternativePlan, ExecutionPlan, Interpretation, PlanningContext

_TOP_WORDS = ("top", "highest", "most", "largest")
_INT_RE = re.compile(r"\b(\d+)\b")
_WORD_RE = re.compile(r"[a-zA-Z_]+")


def indexed_fields(indexes: list[dict]) -> set[str]:
    fields: set[str] = set()
    for idx in indexes:
        for pair in idx.get("key", []):
            fields.add(pair[0] if isinstance(pair, (list, tuple)) else pair)
    return fields


def _detect_limit(intent: str) -> int | None:
    m = _INT_RE.search(intent)
    return int(m.group(1)) if m else None


def _detect_sort(intent: str, schema_fields: dict) -> dict | None:
    lower = intent.lower()
    if not any(w in lower for w in _TOP_WORDS):
        return None
    # sort by a schema field mentioned after "by", else any numeric field mentioned
    tokens = _WORD_RE.findall(lower)
    for tok in tokens:
        if tok in schema_fields:
            return {tok: -1}
    return None


class QueryPlanner:
    def build(self, context: PlanningContext, interpretation: Interpretation | None) -> ExecutionPlan:
        schema_fields = context.resource_schema.get("fields", {}) if context.resource_schema else {}
        idx = indexed_fields(context.indexes)
        filter_: dict | None = None
        if interpretation is not None:
            filter_ = {interpretation.field: interpretation.value}
        sort = _detect_sort(context.intent, schema_fields)
        limit = _detect_limit(context.intent)
        req = CapabilityRequest(
            capability=Capability.READ,
            resource=context.resource or "",
            filter=filter_,
            sort=sort,
            limit=limit,
        )
        index_used: bool | None = None
        if filter_:
            index_used = next(iter(filter_)) in idx
        strategy = "index_scan" if index_used else "collection_scan"
        return ExecutionPlan(
            strategy=strategy,
            request=req,
            index_used=index_used,
            complexity="low" if index_used else "high",
        )


class AlternativePlanner:
    def expand(self, base: ExecutionPlan, context: PlanningContext) -> list[ExecutionPlan]:
        plans: list[ExecutionPlan] = [base]
        filter_ = base.request.filter
        if filter_:
            limit = base.request.limit or 50
            agg_req = CapabilityRequest(
                capability=Capability.AGGREGATE,
                resource=base.request.resource,
                pipeline=[{"$match": filter_}, {"$limit": limit}],
            )
            plans.append(
                AlternativePlan(
                    strategy="aggregation",
                    request=agg_req,
                    complexity="medium",
                    tradeoff="pipeline form; enables downstream $group/$lookup",
                )
            )
        return plans
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_query_planner.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add src/guardmcp/core/planning/planner.py tests/unit/test_query_planner.py
git commit -m "feat(planning): QueryPlanner + AlternativePlanner producing CapabilityRequests"
```

---

### Task 6: RecommendationEngine (`core/planning/recommend.py`)

**Files:**
- Create: `src/guardmcp/core/planning/recommend.py`
- Test: `tests/unit/test_recommendation_engine.py`

**Interfaces:**
- Consumes: `ExecutionPlan`, `AlternativePlan` (Task 1); `CostLevel` (interfaces.cost).
- Produces:
  - `class RecommendationEngine` with `def rank(self, plans: list[ExecutionPlan]) -> list[AlternativePlan]`. Returns AlternativePlans with `rank` set (1-based, best first) and a `tradeoff` explanation; input order preserved as tiebreak.

**Ranking (deterministic, lower score = better):** score each plan by `(governance_penalty, cost_rank, index_penalty)`:
- `governance_penalty`: `denied`→2, `approval_required`→1, else 0 (from `plan.governance.get("decision")`).
- `cost_rank`: map `est_cost.estimated_cost` — LOW=0, MEDIUM=1, HIGH=2, CRITICAL=3, UNKNOWN=2.
- `index_penalty`: 0 if `index_used` is True else 1.
Stable sort by `(score_tuple, original_index)`. First becomes `rank=1`. Fill `tradeoff` if empty: `"index-backed, {cost} cost"` / `"collection scan, {cost} cost"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_recommendation_engine.py
from guardmcp.core.interfaces.capability import Capability, CapabilityRequest
from guardmcp.core.interfaces.cost import CostEstimate, CostLevel
from guardmcp.core.planning.models import ExecutionPlan
from guardmcp.core.planning.recommend import RecommendationEngine


def _plan(strategy, index_used, cost, decision="allowed"):
    return ExecutionPlan(
        strategy=strategy,
        request=CapabilityRequest(capability=Capability.READ, resource="user"),
        index_used=index_used,
        est_cost=CostEstimate(estimated_cost=cost),
        governance={"decision": decision},
    )


def test_index_plan_ranked_above_scan():
    scan = _plan("collection_scan", False, CostLevel.HIGH)
    idx = _plan("index_scan", True, CostLevel.LOW)
    ranked = RecommendationEngine().rank([scan, idx])
    assert ranked[0].strategy == "index_scan"
    assert ranked[0].rank == 1
    assert ranked[1].rank == 2


def test_denied_plan_ranked_last():
    ok = _plan("collection_scan", False, CostLevel.HIGH, decision="allowed")
    denied = _plan("index_scan", True, CostLevel.LOW, decision="denied")
    ranked = RecommendationEngine().rank([denied, ok])
    assert ranked[0].strategy == "collection_scan"


def test_tradeoff_filled_when_empty():
    ranked = RecommendationEngine().rank([_plan("index_scan", True, CostLevel.LOW)])
    assert "index" in ranked[0].tradeoff.lower()


def test_stable_for_equal_scores():
    a = _plan("index_scan", True, CostLevel.LOW)
    b = _plan("index_scan", True, CostLevel.LOW)
    ranked = RecommendationEngine().rank([a, b])
    assert [p.rank for p in ranked] == [1, 2]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_recommendation_engine.py -v`
Expected: FAIL — `ModuleNotFoundError: ...planning.recommend`

- [ ] **Step 3: Write minimal implementation**

```python
# src/guardmcp/core/planning/recommend.py
from __future__ import annotations

from ..interfaces.cost import CostLevel
from .models import AlternativePlan, ExecutionPlan

_COST_RANK = {
    CostLevel.LOW: 0, CostLevel.MEDIUM: 1, CostLevel.HIGH: 2,
    CostLevel.CRITICAL: 3, CostLevel.UNKNOWN: 2,
}
_GOV_PENALTY = {"denied": 2, "approval_required": 1}


class RecommendationEngine:
    def rank(self, plans: list[ExecutionPlan]) -> list[AlternativePlan]:
        def score(plan: ExecutionPlan) -> tuple[int, int, int]:
            gov = _GOV_PENALTY.get(str(plan.governance.get("decision", "")).lower(), 0)
            cost = _COST_RANK.get(plan.est_cost.estimated_cost, 2) if plan.est_cost else 2
            idx = 0 if plan.index_used else 1
            return (gov, cost, idx)

        ordered = sorted(enumerate(plans), key=lambda pair: (score(pair[1]), pair[0]))
        result: list[AlternativePlan] = []
        for rank, (_, plan) in enumerate(ordered, start=1):
            data = plan.model_dump()
            data.pop("rank", None)
            data.pop("tradeoff", None)
            tradeoff = getattr(plan, "tradeoff", "") or self._tradeoff(plan)
            result.append(AlternativePlan(**data, rank=rank, tradeoff=tradeoff))
        return result

    @staticmethod
    def _tradeoff(plan: ExecutionPlan) -> str:
        cost = plan.est_cost.estimated_cost.value if plan.est_cost else "UNKNOWN"
        base = "index-backed" if plan.index_used else "collection scan"
        return f"{base}, {cost} cost"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_recommendation_engine.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/guardmcp/core/planning/recommend.py tests/unit/test_recommendation_engine.py
git commit -m "feat(planning): deterministic RecommendationEngine ranking"
```

---

### Task 7: PlanningPipeline orchestrator (`core/planning/pipeline.py`)

**Files:**
- Create: `src/guardmcp/core/planning/pipeline.py`
- Test: `tests/unit/test_planning_pipeline.py`

**Interfaces:**
- Consumes: all stage classes (Tasks 3–6); `GuardPipeline` (`discover_collections`, `describe_collection`, `evaluate_capability`); `RelationshipResolver`; `_active_plugin`-style plugin getter; `Capability`, `CapabilityRequest`; `DecisionStatus`.
- Produces:
  - `class PlanningPipeline`
    - `__init__(self, guard: GuardPipeline, resolver: RelationshipResolver, get_plugin: Callable[[], object|None], *, ambiguity=None, planner=None, alternatives=None, recommender=None)`
    - `async def plan(self, agent: str, intent: str, resource: str | None = None) -> PlannerResult`
    - `async def relationships(self, agent: str) -> RelationshipGraph`

**Orchestration rules (`plan`):**
1. `allowed = await guard.discover_collections(agent)`. If empty → return degraded `PlannerResult` (empty ambiguity/graph, note "no authorized collections").
2. Choose `resource`: if `resource` given and in `allowed`, use it; elif a token of intent matches an allowed resource, use it; else `allowed[0]` and add note.
3. `desc = await guard.describe_collection(agent, resource)`; `schema_fields = desc.get("fields", {})` (desc may be None → {} + note). Masked fields already excluded by `describe_collection`.
4. `graph = await resolver.graph(allowed)`.
5. `indexes`: best-effort via plugin — see note; on failure `[]` + note. (Use `get_plugin()`; if plugin has `_executor` with `collection_indexes`, call it; wrap in try/except.)
6. `report = ambiguity.detect(intent, schema_fields, indexed_set)`.
7. If `report.ambiguous` → return `PlannerResult(ambiguity=report, relationships=graph, plans=[], recommended_plan=None, notes=[+"clarify"])`. SHORT-CIRCUIT.
8. `interp = report.interpretations[0] if report.interpretations else None`.
9. `base = planner.build(ctx, interp)`; `plans = alternatives.expand(base, ctx)`.
10. For each plan: `est = await plugin.estimate(plan.request)` (guarded → None); `eval = guard.evaluate_capability(agent, plan.request.resource, plan.request.capability, plan.request)`; set `plan.est_cost`, `plan.governance = {"decision": eval.decision.status.value, "reason": eval.decision.reason}`, `plan.risk_level = eval.decision.risk.value if set`. Use `model_copy(update=...)`.
11. `ranked = recommender.rank(plans)`; `recommended = ranked[0] if ranked else None`.
12. Return `PlannerResult(...)`.

`relationships(agent)`: `allowed = await guard.discover_collections(agent)`; `return await resolver.graph(allowed)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_planning_pipeline.py
import pytest

from guardmcp.core.interfaces.capability import Capability
from guardmcp.core.interfaces.cost import CostEstimate, CostLevel
from guardmcp.core.models.domain import Decision, DecisionStatus
from guardmcp.core.planning.models import RelationshipGraph
from guardmcp.core.planning.pipeline import PlanningPipeline
from guardmcp.core.planning.relationships import RelationshipResolver
from guardmcp.core.pipeline import EvalResult
from guardmcp.core.models.domain import Action, Request


class _Guard:
    def __init__(self, allowed, fields, decision=DecisionStatus.ALLOWED):
        self._allowed = allowed
        self._fields = fields
        self._decision = decision

    async def discover_collections(self, agent):
        return list(self._allowed)

    async def describe_collection(self, agent, collection):
        return {"fields": self._fields}

    def evaluate_capability(self, agent, resource, capability, request=None):
        return EvalResult(
            request=Request(agent=agent, collection=resource, action=Action.FIND, params={}),
            decision=Decision(status=self._decision, reason="ok"),
            policy=None,
        )


class _Executor:
    async def collection_indexes(self, collection):
        return [{"name": "status_1", "key": [("status", 1)]}]


class _Plugin:
    def __init__(self):
        self._executor = _Executor()
    async def relationships(self, resources):
        return []
    async def estimate(self, req):
        return CostEstimate(estimated_cost=CostLevel.LOW, index_used=True)


def _pipeline(guard, plugin):
    return PlanningPipeline(guard, RelationshipResolver(lambda: plugin), lambda: plugin)


@pytest.mark.asyncio
async def test_plan_returns_ranked_plans_when_unambiguous():
    guard = _Guard(["user"], {"status": "string"})
    res = await _pipeline(guard, _Plugin()).plan("claude", "show active users")
    assert res.ambiguity.ambiguous is False
    assert res.recommended_plan is not None
    assert res.recommended_plan.request.filter == {"status": "ACTIVE"}
    assert res.recommended_plan.governance["decision"] == "allowed"
    assert res.recommended_plan.est_cost.estimated_cost == CostLevel.LOW


@pytest.mark.asyncio
async def test_plan_short_circuits_when_ambiguous():
    guard = _Guard(["user"], {"status": "string", "is_active": "bool"})
    res = await _pipeline(guard, _Plugin()).plan("claude", "show active users")
    assert res.ambiguity.ambiguous is True
    assert res.plans == []
    assert res.recommended_plan is None


@pytest.mark.asyncio
async def test_plan_degrades_with_no_allowed_collections():
    guard = _Guard([], {})
    res = await _pipeline(guard, _Plugin()).plan("claude", "show active users")
    assert res.plans == []
    assert any("authorized" in n.lower() for n in res.notes)


@pytest.mark.asyncio
async def test_relationships_uses_allowed_only():
    guard = _Guard(["user", "project"], {})
    g = await _pipeline(guard, _Plugin()).relationships("claude")
    assert isinstance(g, RelationshipGraph)
    assert set(g.nodes) == {"user", "project"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_planning_pipeline.py -v`
Expected: FAIL — `ModuleNotFoundError: ...planning.pipeline`

- [ ] **Step 3: Write minimal implementation**

```python
# src/guardmcp/core/planning/pipeline.py
from __future__ import annotations

import re
from collections.abc import Callable
from typing import TYPE_CHECKING

from ..models.domain import DecisionStatus
from .ambiguity import AmbiguityDetector
from .models import PlannerResult, PlanningContext, RelationshipGraph
from .planner import AlternativePlanner, QueryPlanner, indexed_fields
from .recommend import RecommendationEngine
from .relationships import RelationshipResolver

if TYPE_CHECKING:
    from ..pipeline import GuardPipeline

_WORD_RE = re.compile(r"[a-zA-Z_]+")


class PlanningPipeline:
    def __init__(
        self,
        guard: "GuardPipeline",
        resolver: RelationshipResolver,
        get_plugin: Callable[[], object | None],
        *,
        ambiguity: AmbiguityDetector | None = None,
        planner: QueryPlanner | None = None,
        alternatives: AlternativePlanner | None = None,
        recommender: RecommendationEngine | None = None,
    ) -> None:
        self._guard = guard
        self._resolver = resolver
        self._get_plugin = get_plugin
        self._ambiguity = ambiguity or AmbiguityDetector()
        self._planner = planner or QueryPlanner()
        self._alternatives = alternatives or AlternativePlanner()
        self._recommender = recommender or RecommendationEngine()

    async def relationships(self, agent: str) -> RelationshipGraph:
        allowed = await self._guard.discover_collections(agent)
        return await self._resolver.graph(allowed)

    def _pick_resource(self, intent: str, resource: str | None, allowed: list[str], notes: list[str]) -> str:
        if resource and resource in allowed:
            return resource
        if resource and resource not in allowed:
            notes.append(f"requested resource '{resource}' not authorized; picking another")
        tokens = set(_WORD_RE.findall(intent.lower()))
        for r in allowed:
            if r.lower() in tokens or r.lower().rstrip("s") in tokens:
                return r
        notes.append(f"no resource named in intent; defaulted to '{allowed[0]}'")
        return allowed[0]

    async def _indexes_for(self, resource: str, notes: list[str]) -> list[dict]:
        plugin = self._get_plugin()
        executor = getattr(plugin, "_executor", None)
        getter = getattr(executor, "collection_indexes", None)
        if getter is None:
            return []
        try:
            return await getter(resource)
        except Exception:
            notes.append(f"index introspection failed for '{resource}'")
            return []

    async def plan(self, agent: str, intent: str, resource: str | None = None) -> PlannerResult:
        notes: list[str] = []
        empty_graph = RelationshipGraph(nodes=[], edges=[], generated_at="")
        from .models import AmbiguityReport

        allowed = await self._guard.discover_collections(agent)
        if not allowed:
            notes.append("no authorized collections for this agent")
            return PlannerResult(
                ambiguity=AmbiguityReport(ambiguous=False, confidence=1.0),
                relationships=empty_graph, notes=notes,
            )

        chosen = self._pick_resource(intent, resource, allowed, notes)
        desc = await self._guard.describe_collection(agent, chosen)
        schema_fields = (desc or {}).get("fields", {})
        if desc is None:
            notes.append(f"no schema available for '{chosen}'")

        graph = await self._resolver.graph(allowed)
        indexes = await self._indexes_for(chosen, notes)
        idx_set = indexed_fields(indexes)

        report = self._ambiguity.detect(intent, schema_fields, idx_set)
        if report.ambiguous:
            notes.append("intent is ambiguous; returning interpretations for clarification")
            return PlannerResult(ambiguity=report, relationships=graph, notes=notes)

        ctx = PlanningContext(
            agent=agent, intent=intent, resource=chosen, allowed_resources=allowed,
            resource_schema={"fields": schema_fields}, indexes=indexes, relationships=graph,
        )
        interp = report.interpretations[0] if report.interpretations else None
        base = self._planner.build(ctx, interp)
        plans = self._alternatives.expand(base, ctx)

        plugin = self._get_plugin()
        enriched = []
        for plan in plans:
            est = None
            if plugin is not None and hasattr(plugin, "estimate"):
                try:
                    est = await plugin.estimate(plan.request)
                except Exception:
                    est = None
            ev = self._guard.evaluate_capability(agent, plan.request.resource, plan.request.capability, plan.request)
            gov = {"decision": ev.decision.status.value, "reason": ev.decision.reason}
            risk = ev.decision.risk.value if ev.decision.risk else None
            enriched.append(plan.model_copy(update={"est_cost": est, "governance": gov, "risk_level": risk}))

        ranked = self._recommender.rank(enriched)
        recommended = ranked[0] if ranked else None
        return PlannerResult(
            ambiguity=report, relationships=graph, plans=ranked,
            recommended_plan=recommended, notes=notes,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_planning_pipeline.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/guardmcp/core/planning/pipeline.py tests/unit/test_planning_pipeline.py
git commit -m "feat(planning): PlanningPipeline orchestrator (governed, no execution)"
```

---

### Task 8: MCP tools `guardmcp_plan_query` + `guardmcp_relationships`

**Files:**
- Create: `src/guardmcp/server/tools/meta/plan_query.py`
- Modify: `src/guardmcp/server/tools/meta/__init__.py` (register the new module)
- Test: `tests/unit/test_plan_query_tool.py`

**Interfaces:**
- Consumes: `ToolContext`, `ok`, `err`, `ErrorCode`, `_active_plugin` from `.._common`; `PlanningPipeline`, `RelationshipResolver` (Tasks 3, 7); `FastMCP`.
- Produces: module-level `register(mcp, ctx)` that registers two read-only tools returning envelope JSON strings.

**Rules:** Build the `PlanningPipeline` per call from `ctx.get_pipeline()` and a plugin getter `lambda: _active_plugin(pipeline)`. `guardmcp_plan_query(intent: str, resource: str | None = None)` → `ok(result.model_dump(mode="json"))`. `guardmcp_relationships(resource: str | None = None)` → `ok({"relationships": graph.model_dump(mode="json")})`. Both wrapped so exceptions become `err(ErrorCode.BACKEND_ERROR, ...)`. Look at existing `meta/plan.py` and `meta/__init__.py` for the exact registration pattern before editing.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_plan_query_tool.py
import json

import pytest
from mcp.server.fastmcp import FastMCP

from guardmcp.core.interfaces.cost import CostEstimate, CostLevel
from guardmcp.core.models.domain import Action, Decision, DecisionStatus, Request
from guardmcp.core.pipeline import EvalResult
from guardmcp.server.tools._common import ToolContext
from guardmcp.server.tools.meta import plan_query


class _Executor:
    async def collection_indexes(self, collection):
        return [{"name": "status_1", "key": [("status", 1)]}]


class _Plugin:
    name = "mongodb"
    def __init__(self):
        self._executor = _Executor()
    async def relationships(self, resources):
        return []
    async def estimate(self, req):
        return CostEstimate(estimated_cost=CostLevel.LOW)


class _Entry:
    plugin = _Plugin()


class _Registry:
    def get_active(self):
        return _Entry()


class _Pipeline:
    _registry = _Registry()
    async def discover_collections(self, agent):
        return ["user"]
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
    ctx = ToolContext(get_pipeline=lambda: _Pipeline(), get_agent=lambda: "claude",
                      get_settings=lambda: None)
    plan_query.register(mcp, ctx)
    return mcp


@pytest.mark.asyncio
async def test_plan_query_tool_returns_recommended_plan():
    mcp = _register()
    tool = await mcp.get_tool("guardmcp_plan_query")
    out = json.loads(await tool.run({"intent": "show active users"}))
    assert out["status"] == "success"
    assert out["data"]["recommended_plan"]["request"]["filter"] == {"status": "ACTIVE"}


@pytest.mark.asyncio
async def test_relationships_tool_returns_graph():
    mcp = _register()
    tool = await mcp.get_tool("guardmcp_relationships")
    out = json.loads(await tool.run({}))
    assert out["status"] == "success"
    assert out["data"]["relationships"]["nodes"] == ["user"]
```

> Note: confirm the FastMCP test-invocation API (`mcp.get_tool(...).run({...})`) against the existing `tests/unit/test_mcp_tooling.py`; if that suite calls tools differently, mirror its exact pattern here.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_plan_query_tool.py -v`
Expected: FAIL — `ImportError: cannot import name 'plan_query'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/guardmcp/server/tools/meta/plan_query.py
"""guardmcp_plan_query — NL intent → ambiguity, relationships, ranked plans.

Deterministic, no-LLM. NEVER executes queries; only reads authorized metadata,
estimates cost (explain), and evaluates governance per candidate plan.
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ....core.planning.pipeline import PlanningPipeline
from ....core.planning.relationships import RelationshipResolver
from .._common import ErrorCode, ToolContext, _active_plugin, err, ok


def register(mcp: FastMCP, ctx: ToolContext) -> None:
    get_pipeline = ctx.get_pipeline
    get_agent = ctx.get_agent
    _RO = ctx.RO

    def _build_planning_pipeline():
        pipeline = get_pipeline()
        get_plugin = lambda: _active_plugin(pipeline)  # noqa: E731
        resolver = RelationshipResolver(get_plugin)
        return PlanningPipeline(pipeline, resolver, get_plugin), get_agent()

    @mcp.tool(
        description=(
            "Plan a query from a natural-language intent WITHOUT executing it. "
            "Returns detected ambiguity (with interpretations to clarify), a "
            "relationship graph, ranked candidate execution plans (each with cost, "
            "index usage, and governance impact), and a recommended plan.\n"
            "Use when: deciding HOW to query before running read/aggregate ops.\n"
            "Do NOT use when: you already know the exact op — call guardmcp_plan.\n"
            "Side effects: none — never executes; only reads metadata + explain.\n"
            "Example: guardmcp_plan_query(intent='show active users')"
        ),
        annotations=_RO,
    )
    async def guardmcp_plan_query(intent: str, resource: str | None = None) -> str:
        try:
            planner, agent = _build_planning_pipeline()
            result = await planner.plan(agent, intent, resource)
            return ok(result.model_dump(mode="json"))
        except Exception as exc:  # planning must never crash the server
            return err(ErrorCode.BACKEND_ERROR, f"planning failed: {type(exc).__name__}",
                       retryable=True)

    @mcp.tool(
        description=(
            "Return the discovered relationship graph among the collections this "
            "agent is authorized to see (diagnostic / visualization).\n"
            "Side effects: none.\n"
            "Example: guardmcp_relationships()"
        ),
        annotations=_RO,
    )
    async def guardmcp_relationships(resource: str | None = None) -> str:
        try:
            planner, agent = _build_planning_pipeline()
            graph = await planner.relationships(agent)
            return ok({"relationships": graph.model_dump(mode="json")})
        except Exception as exc:
            return err(ErrorCode.BACKEND_ERROR, f"relationship discovery failed: {type(exc).__name__}",
                       retryable=True)
```

Modify `src/guardmcp/server/tools/meta/__init__.py` — mirror how `plan` is imported+registered and add `plan_query` alongside it. Read the file first; add `from . import plan_query` and call `plan_query.register(mcp, ctx)` in the same place the other meta modules are registered.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_plan_query_tool.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/guardmcp/server/tools/meta/plan_query.py src/guardmcp/server/tools/meta/__init__.py tests/unit/test_plan_query_tool.py
git commit -m "feat(planning): guardmcp_plan_query + guardmcp_relationships MCP tools"
```

---

### Task 9: Adversarial + integration tests (security: no denied/masked leak)

**Files:**
- Create: `tests/integration/test_planning_security.py`

**Interfaces:**
- Consumes: `PlanningPipeline`, `RelationshipResolver` (Tasks 3, 7); a fake `GuardPipeline` whose `discover_collections`/`describe_collection` enforce allow/deny + masking (mirrors the real governed accessors).

**What it proves:**
1. A denied collection never appears in relationships nodes/edges even if the plugin reports an edge to it.
2. A masked field is never proposed as an ambiguity interpretation (because `describe_collection` omits it).
3. An intent naming a denied collection falls back to an allowed one + notes, never plans against the denied one.
4. Every returned plan's `governance.decision` equals what `evaluate_capability` returns for that request.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_planning_security.py
import pytest

from guardmcp.core.interfaces.cost import CostEstimate, CostLevel
from guardmcp.core.models.domain import Action, Decision, DecisionStatus, Request
from guardmcp.core.pipeline import EvalResult
from guardmcp.core.planning.pipeline import PlanningPipeline
from guardmcp.core.planning.relationships import RelationshipResolver

ALLOWED = {"user", "project"}
DENIED = {"secrets"}


class _Executor:
    async def collection_indexes(self, collection):
        return []


class _Plugin:
    def __init__(self):
        self._executor = _Executor()
    async def relationships(self, resources):
        # Maliciously report an edge to a denied collection.
        return [{"from_resource": "user", "from_field": "secret_id", "to_resource": "secrets",
                 "to_field": "_id", "kind": "naming", "confidence": 0.5, "evidence": "x"}]
    async def estimate(self, req):
        return CostEstimate(estimated_cost=CostLevel.LOW)


class _GovGuard:
    """Mimics governed accessors: only ALLOWED collections, masked field hidden."""
    async def discover_collections(self, agent):
        return sorted(ALLOWED)
    async def describe_collection(self, agent, collection):
        if collection not in ALLOWED:
            return None
        # 'password' is masked → excluded from schema by the real accessor.
        return {"fields": {"status": "string"}}
    def evaluate_capability(self, agent, resource, capability, request=None):
        status = DecisionStatus.DENIED if resource in DENIED else DecisionStatus.ALLOWED
        return EvalResult(
            request=Request(agent=agent, collection=resource, action=Action.FIND, params={}),
            decision=Decision(status=status, reason="policy"),
            policy=None,
        )


def _pipeline():
    plugin = _Plugin()
    return PlanningPipeline(_GovGuard(), RelationshipResolver(lambda: plugin), lambda: plugin)


@pytest.mark.asyncio
async def test_denied_collection_never_in_relationships():
    g = await _pipeline().relationships("claude")
    assert "secrets" not in g.nodes
    assert all(e.to_resource != "secrets" for e in g.edges)


@pytest.mark.asyncio
async def test_masked_field_not_in_interpretations():
    res = await _pipeline().plan("claude", "show users with password active")
    fields = {i.field for i in res.ambiguity.interpretations}
    assert "password" not in fields


@pytest.mark.asyncio
async def test_intent_naming_denied_collection_falls_back():
    res = await _pipeline().plan("claude", "read secrets", resource="secrets")
    if res.recommended_plan is not None:
        assert res.recommended_plan.request.resource in ALLOWED
    assert any("not authorized" in n.lower() for n in res.notes)


@pytest.mark.asyncio
async def test_plan_governance_matches_evaluate():
    res = await _pipeline().plan("claude", "show active users")
    for p in res.plans:
        assert p.governance["decision"] == "allowed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_planning_security.py -v`
Expected: FAIL only if a bug exists; if Tasks 1–8 are correct these should PASS. If any FAIL, fix the implicated stage (do NOT weaken the test). First run may error on import until prior tasks are merged.

- [ ] **Step 3: Make failing assertions pass**

No new production code expected. If `test_denied_collection_never_in_relationships` fails, verify Task 3's allowed-set edge filter. If `test_intent_naming_denied_collection_falls_back` fails, verify Task 7 `_pick_resource` notes + fallback. Fix the specific stage.

- [ ] **Step 4: Run the full planning suite**

Run: `python -m pytest tests/unit/test_planning_models.py tests/unit/test_mongo_relationships.py tests/unit/test_relationship_resolver.py tests/unit/test_ambiguity_detector.py tests/unit/test_query_planner.py tests/unit/test_recommendation_engine.py tests/unit/test_planning_pipeline.py tests/unit/test_plan_query_tool.py tests/integration/test_planning_security.py -v`
Expected: ALL PASS. Then `ruff check src tests`.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_planning_security.py
git commit -m "test(planning): adversarial security + governance-parity integration tests"
```

---

## Self-Review

**Spec coverage:** ambiguity (T4), relationships (T2+T3), safe planner/IR (T1+T5), alternatives (T5), recommendation (T6), MCP tools one-orchestrator + diagnostic (T8), plugin seam Mongo-only + safe default (T2), governance no-bypass + per-plan eval (T7), no-leak security (T9), caching + invalidation (T3), determinism (T4/T6 tests), degradation-not-crash (T7). Deferred by design (documented in spec, not this plan): Postgres/MySQL metadata impl, eval-harness metric cases, sampling-based relationships.

**Placeholders:** none — every code step is complete. Two steps intentionally instruct reading an existing file before a small edit (`meta/__init__.py` registration, FastMCP call pattern) because the exact local convention must be matched; the change itself is specified.

**Type consistency:** `indexed_fields()` defined once (T5) and reused (T7). `Relationship`/`RelationshipGraph`/`ExecutionPlan`/`AlternativePlan`/`PlannerResult` names consistent across T1→T9. `governance` dict shape `{"decision","reason"}` consistent T7↔T9. `plugin.relationships()` return-dict keys consistent T2↔T3.
