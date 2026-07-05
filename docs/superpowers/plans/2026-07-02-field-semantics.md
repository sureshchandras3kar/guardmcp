# Field Semantics (Context Engine, Slice 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deterministically infer each field's semantic role (primary/foreign identifier, tenant key, timestamp, enum/status, PII) from runtime metadata + the existing sample, and surface it additively in the collection-schema output — so an AI client learns what fields *mean* before querying.

**Architecture:** A pure, database-agnostic `FieldSemanticsAnalyzer` in new `core/context/` consumes only normalized inputs (field types, indexes, relationship edges + fan-in, per-field sample stats, masked-field names) and returns per-field semantics. A new optional `DatabasePlugin.field_stats()` seam (safe default `{}`) is implemented for MongoDB by computing stats from the SAME sample `MongoSchemaCache` already draws (no new reads). `GuardPipeline.describe_collection` assembles the inputs and attaches `semantics` + `masked_fields` to its output.

**Tech Stack:** Python 3.12+, Pydantic v2, pytest/pytest-asyncio, MongoDB (motor).

## Global Constraints

- Data-agnostic: NO hardcoded collection/field names, NO product-specific tokens, NO fixed enum value lists. Detection is structural-first; generic English name tokens are confidence *boosters* only and must only fire when the field exists in the live schema.
- Deterministic, NO AI/LLM. Same inputs → identical output.
- Governance: masked fields are labelled `pii` by NAME only; their values are NEVER sampled, counted for distinct, or emitted. Denied collections yield nothing.
- No new database reads: MongoDB `field_stats` reuses the sample `MongoSchemaCache._sample_schema` already fetches.
- Backward compatible: `DatabasePlugin.field_stats` default `{}`; schema output changes are ADDITIVE (`semantics`, `masked_fields` keys) — existing `fields` map unchanged.
- Analyzer is pure (no I/O); core `context/` package has NO Mongo/SQL imports.
- Run tests with `/Users/suresh/guardmcp/.venv/bin/python -m pytest <path> -v`. Lint: `/Users/suresh/guardmcp/.venv/bin/python -m ruff check src tests`. (No `python` on PATH — always use the venv interpreter.)
- Codebase-orientation rule (repo mandate): before reading a source file to understand it, run `graphify query "<question>"` first; if graphify is unavailable in the shell, read the specific file directly. Applies to subagents too.
- Commit message bodies end with: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

## Constants (fixed, documented)

- `TENANT_FANIN_MIN = 3` — a foreign field referenced by ≥3 collections is a tenant/scope key.
- `ENUM_MAX_DISTINCT = 12` — string field with ≤12 distinct sample values is an enum.
- `NEAR_UNIQUE_RATIO = 0.95` — distinct/count ≥ this ⇒ near-unique (identifier).
- `ENUM_VALUES_CAP = 20` — max enum values emitted.
- `ENUM_TRACK_CAP = 50` — stop tracking distinct values past this (overflow ⇒ distinct unknown).

---

### Task 1: Context models (`core/context/models.py`)

**Files:**
- Create: `src/guardmcp/core/context/__init__.py`
- Create: `src/guardmcp/core/context/models.py`
- Test: `tests/unit/test_context_models.py`

**Interfaces:**
- Produces:
  - `FieldStat(count:int, null_count:int=0, distinct_count:int|None=None, sample_values:list|None=None)`
  - `FieldSemantics(role:str, confidence:float=0.0, evidence:str="", references:str|None=None, values:list|None=None, pii:bool=False)`
  - `SemanticsInput(resource:str, fields:dict[str,str], indexes:list[dict]=[], edges:list[dict]=[], fan_in:dict[str,int]={}, field_stats:dict[str,FieldStat]={}, masked_fields:list[str]=[])`
  - `SemanticsResult(fields:dict[str,FieldSemantics])`
  - Role constants module-level: `ROLE_PRIMARY="primary_identifier"`, `ROLE_FOREIGN="foreign_identifier"`, `ROLE_TENANT="tenant_key"`, `ROLE_TIMESTAMP="timestamp"`, `ROLE_ENUM="enum_status"`, `ROLE_PII="pii"`, `ROLE_NONE="none"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_context_models.py
from guardmcp.core.context.models import (
    FieldSemantics, FieldStat, SemanticsInput, SemanticsResult, ROLE_FOREIGN, ROLE_NONE,
)


def test_field_stat_defaults():
    s = FieldStat(count=10)
    assert s.null_count == 0 and s.distinct_count is None and s.sample_values is None


def test_field_semantics_defaults():
    fs = FieldSemantics(role=ROLE_NONE)
    assert fs.confidence == 0.0 and fs.pii is False and fs.references is None and fs.values is None


def test_semantics_input_defaults():
    inp = SemanticsInput(resource="user", fields={"_id": "objectId"})
    assert inp.indexes == [] and inp.edges == [] and inp.fan_in == {} and inp.masked_fields == []


def test_semantics_result_holds_map():
    r = SemanticsResult(fields={"user_id": FieldSemantics(role=ROLE_FOREIGN, references="user")})
    assert r.fields["user_id"].references == "user"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest tests/unit/test_context_models.py -v`
Expected: FAIL — `ModuleNotFoundError: guardmcp.core.context`

- [ ] **Step 3: Write minimal implementation**

```python
# src/guardmcp/core/context/__init__.py
"""Context Engine — deterministic, no-LLM database understanding (database-agnostic)."""
```

```python
# src/guardmcp/core/context/models.py
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

ROLE_PRIMARY = "primary_identifier"
ROLE_FOREIGN = "foreign_identifier"
ROLE_TENANT = "tenant_key"
ROLE_TIMESTAMP = "timestamp"
ROLE_ENUM = "enum_status"
ROLE_PII = "pii"
ROLE_NONE = "none"


class FieldStat(BaseModel):
    count: int
    null_count: int = 0
    distinct_count: int | None = None  # None = unknown/overflow
    sample_values: list[Any] | None = None


class FieldSemantics(BaseModel):
    role: str
    confidence: float = 0.0
    evidence: str = ""
    references: str | None = None  # target resource for foreign/tenant
    values: list[Any] | None = None  # enum value set (capped)
    pii: bool = False


class SemanticsInput(BaseModel):
    resource: str
    fields: dict[str, str] = Field(default_factory=dict)
    indexes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)  # this resource's outgoing FK edges
    fan_in: dict[str, int] = Field(default_factory=dict)  # field name -> #collections referencing it
    field_stats: dict[str, FieldStat] = Field(default_factory=dict)
    masked_fields: list[str] = Field(default_factory=list)


class SemanticsResult(BaseModel):
    fields: dict[str, FieldSemantics] = Field(default_factory=dict)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest tests/unit/test_context_models.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/guardmcp/core/context/__init__.py src/guardmcp/core/context/models.py tests/unit/test_context_models.py
git commit -m "feat(context): field-semantics models"
```

---

### Task 2: FieldSemanticsAnalyzer (`core/context/semantics.py`)

**Files:**
- Create: `src/guardmcp/core/context/semantics.py`
- Test: `tests/unit/test_field_semantics_analyzer.py`

**Interfaces:**
- Consumes: `SemanticsInput`, `SemanticsResult`, `FieldStat`, `FieldSemantics`, role constants (Task 1).
- Produces: `class FieldSemanticsAnalyzer` with `def analyze(self, inp: SemanticsInput) -> SemanticsResult`. Also module constants `TENANT_FANIN_MIN`, `ENUM_MAX_DISTINCT`, `NEAR_UNIQUE_RATIO`, `ENUM_VALUES_CAP`.

**Algorithm (per field, priority-ordered, structural-first):** masked → pii (name only). `_id` → primary (1.0). In `edges` → foreign, unless `fan_in[field] >= TENANT_FANIN_MIN` → tenant. Single-field unique index + near-unique sample → primary. `date`/`datetime` type → timestamp (name booster for time-like names). string + enum-cardinality → enum with values. Else none. Generic name tokens only nudge confidence. Independent `pii` bool flag set whenever the name looks PII.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_field_semantics_analyzer.py
from guardmcp.core.context.models import FieldStat, SemanticsInput
from guardmcp.core.context.semantics import FieldSemanticsAnalyzer
from guardmcp.core.context.models import (
    ROLE_PRIMARY, ROLE_FOREIGN, ROLE_TENANT, ROLE_TIMESTAMP, ROLE_ENUM, ROLE_PII, ROLE_NONE,
)

A = FieldSemanticsAnalyzer()


def test_id_is_primary():
    r = A.analyze(SemanticsInput(resource="user", fields={"_id": "objectId"}))
    assert r.fields["_id"].role == ROLE_PRIMARY and r.fields["_id"].confidence == 1.0


def test_edge_field_is_foreign_with_reference():
    inp = SemanticsInput(resource="orders", fields={"user_id": "objectId"},
        edges=[{"from_field": "user_id", "to_resource": "user", "confidence": 0.75}])
    fs = A.analyze(inp).fields["user_id"]
    assert fs.role == ROLE_FOREIGN and fs.references == "user" and fs.confidence == 0.75


def test_high_fanin_foreign_is_tenant_structurally():
    # product-neutral name proves structural (not name-based) detection
    inp = SemanticsInput(resource="orders", fields={"grp": "objectId"},
        edges=[{"from_field": "grp", "to_resource": "grpx", "confidence": 0.75}],
        fan_in={"grp": 5})
    fs = A.analyze(inp).fields["grp"]
    assert fs.role == ROLE_TENANT and fs.references == "grpx"


def test_date_type_is_timestamp():
    r = A.analyze(SemanticsInput(resource="user", fields={"xts": "date"}))
    assert r.fields["xts"].role == ROLE_TIMESTAMP


def test_low_cardinality_string_is_enum_with_values():
    inp = SemanticsInput(resource="user", fields={"st": "string"},
        field_stats={"st": FieldStat(count=100, distinct_count=2, sample_values=["A", "B"])})
    fs = A.analyze(inp).fields["st"]
    assert fs.role == ROLE_ENUM and set(fs.values) == {"A", "B"}


def test_unique_index_near_unique_is_primary():
    inp = SemanticsInput(resource="user", fields={"xref": "string"},
        indexes=[{"name": "xref_1", "key": [("xref", 1)], "unique": True}],
        field_stats={"xref": FieldStat(count=100, distinct_count=100)})
    assert A.analyze(inp).fields["xref"].role == ROLE_PRIMARY


def test_masked_field_is_pii_name_only():
    inp = SemanticsInput(resource="user", fields={"password": "masked"}, masked_fields=["password"])
    fs = A.analyze(inp).fields["password"]
    assert fs.role == ROLE_PII and fs.values is None


def test_pii_name_sets_flag():
    fs = A.analyze(SemanticsInput(resource="user", fields={"email": "string"})).fields["email"]
    assert fs.pii is True


def test_plain_field_is_none():
    fs = A.analyze(SemanticsInput(resource="user", fields={"notes": "string"})).fields["notes"]
    assert fs.role == ROLE_NONE


def test_deterministic():
    inp = SemanticsInput(resource="user", fields={"_id": "objectId", "st": "string"},
        field_stats={"st": FieldStat(count=10, distinct_count=2, sample_values=["A", "B"])})
    assert A.analyze(inp).model_dump() == A.analyze(inp).model_dump()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest tests/unit/test_field_semantics_analyzer.py -v`
Expected: FAIL — `ModuleNotFoundError: ...context.semantics`

- [ ] **Step 3: Write minimal implementation**

```python
# src/guardmcp/core/context/semantics.py
from __future__ import annotations

import re

from .models import (
    ROLE_ENUM, ROLE_FOREIGN, ROLE_NONE, ROLE_PII, ROLE_PRIMARY, ROLE_TENANT, ROLE_TIMESTAMP,
    FieldSemantics, SemanticsInput, SemanticsResult,
)

TENANT_FANIN_MIN = 3
ENUM_MAX_DISTINCT = 12
NEAR_UNIQUE_RATIO = 0.95
ENUM_VALUES_CAP = 20

# Generic (product-neutral) name tokens — BOOSTERS only, never required.
_PII_RE = re.compile(r"(email|e_mail|ssn|social|phone|mobile|credit|card|passw|secret|token|api_?key)", re.I)
_SCOPE_RE = re.compile(r"(tenant|account|organi[sz]ation|org|customer|workspace|company)", re.I)
_ID_RE = re.compile(r"(^id$|_id$|Id$|uuid|guid|(^|_)key$)", re.I)
_TIME_RE = re.compile(r"(_at$|_time$|timestamp|created|updated|modified|date)", re.I)
_STATUS_RE = re.compile(r"(status|state|type|kind|level|mode|stage|phase)", re.I)


def _looks_pii(field: str) -> bool:
    return bool(_PII_RE.search(field))


def _unique_single_index_fields(indexes: list[dict]) -> set[str]:
    out: set[str] = set()
    for idx in indexes:
        if not idx.get("unique"):
            continue
        keys = idx.get("key", [])
        if len(keys) == 1:
            pair = keys[0]
            out.add(pair[0] if isinstance(pair, (list, tuple)) else pair)
    return out


class FieldSemanticsAnalyzer:
    def analyze(self, inp: SemanticsInput) -> SemanticsResult:
        masked = set(inp.masked_fields)
        fk_by_field = {e["from_field"]: e for e in inp.edges if "from_field" in e}
        unique_single = _unique_single_index_fields(inp.indexes)
        out: dict[str, FieldSemantics] = {}

        for field, ftype in inp.fields.items():
            # Masked → pii by NAME ONLY. Never inspect stats/values.
            if field in masked:
                out[field] = FieldSemantics(
                    role=ROLE_PII, confidence=1.0, evidence="policy-masked field", pii=True
                )
                continue

            pii = _looks_pii(field)
            role, conf, ev, refs, values = ROLE_NONE, 0.0, "", None, None
            stat = inp.field_stats.get(field)

            if field == "_id":
                role, conf, ev = ROLE_PRIMARY, 1.0, "document identity field '_id'"
            elif field in fk_by_field:
                edge = fk_by_field[field]
                refs = edge.get("to_resource")
                fin = inp.fan_in.get(field, 0)
                if fin >= TENANT_FANIN_MIN:
                    role = ROLE_TENANT
                    conf = min(0.9, 0.5 + 0.08 * fin)
                    ev = f"foreign identifier referenced across {fin} collections"
                    if _SCOPE_RE.search(field):
                        conf = min(0.95, conf + 0.1)
                        ev += " + generic scope-token name"
                else:
                    role = ROLE_FOREIGN
                    conf = float(edge.get("confidence", 0.5))
                    ev = f"foreign-key edge to '{refs}'"
            elif field in unique_single and stat and _near_unique(stat):
                role, conf, ev = ROLE_PRIMARY, 0.8, "single-field unique index, near-unique in sample"
                if _ID_RE.search(field):
                    conf = min(0.9, conf + 0.1)
                    ev += " + id-like name"
            elif ftype in ("date", "datetime"):
                role, conf, ev = ROLE_TIMESTAMP, 0.9, "date/datetime type"
            elif _TIME_RE.search(field):
                role, conf, ev = ROLE_TIMESTAMP, 0.6, "time-like name"
            elif ftype == "string" and _is_enum(stat):
                role = ROLE_ENUM
                conf = 0.7
                values = list(stat.sample_values or [])[:ENUM_VALUES_CAP]
                ev = f"low-cardinality string ({stat.distinct_count} distinct in sample)"
                if _STATUS_RE.search(field):
                    conf = min(0.85, conf + 0.1)
                    ev += " + status-like name"

            out[field] = FieldSemantics(
                role=role, confidence=round(conf, 4), evidence=ev,
                references=refs, values=values, pii=pii,
            )
        return SemanticsResult(fields=out)


def _near_unique(stat) -> bool:
    if stat is None or stat.distinct_count is None or stat.count <= 0:
        return False
    return (stat.distinct_count / stat.count) >= NEAR_UNIQUE_RATIO


def _is_enum(stat) -> bool:
    if stat is None or stat.distinct_count is None or stat.count <= 0:
        return False
    return 0 < stat.distinct_count <= ENUM_MAX_DISTINCT and stat.distinct_count < stat.count
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest tests/unit/test_field_semantics_analyzer.py -v`
Expected: PASS (10 passed)

- [ ] **Step 5: Commit**

```bash
git add src/guardmcp/core/context/semantics.py tests/unit/test_field_semantics_analyzer.py
git commit -m "feat(context): deterministic structural-first FieldSemanticsAnalyzer"
```

---

### Task 3: MongoDB `field_stats` (seam + masking-aware sample stats)

**Files:**
- Modify: `src/guardmcp/core/interfaces/plugin.py` (add default `field_stats` after `relationships`)
- Modify: `src/guardmcp/plugins/mongodb/schema.py` (add `build_field_stats`)
- Modify: `src/guardmcp/plugins/mongodb/schema_cache.py` (compute+cache raw stats in `_sample_schema`; add `field_stats`)
- Modify: `src/guardmcp/plugins/mongodb/executor.py` (add `field_stats` delegating to schema cache)
- Modify: `src/guardmcp/plugins/mongodb/plugin.py` (implement `field_stats`)
- Test: `tests/unit/test_field_stats.py`

**Interfaces:**
- Produces:
  - `build_field_stats(raw_docs: list[dict], mask_fields: list[str]) -> dict[str, dict]` — each value `{"count","null_count","distinct_count","sample_values"}`; masked fields get `distinct_count=None, sample_values=None` and no values recorded.
  - `MongoSchemaCache.field_stats(collection: str, mask_fields: list[str], sample_size: int|None=None) -> dict[str, dict]`
  - `MongoExecutor.field_stats(collection: str, mask_fields: list[str]) -> dict[str, dict]`
  - `MongoPlugin.field_stats(resource: str, mask_fields: list[str]|None=None) -> dict[str, dict]`
  - `DatabasePlugin.field_stats(self, resource: str, mask_fields: list[str]|None=None) -> dict` default `{}`.

**Orientation:** run `graphify query "MongoSchemaCache _sample_schema caching tuple"` before editing; if graphify unavailable, read `src/guardmcp/plugins/mongodb/schema_cache.py` directly. The cache currently stores `(raw_schema, type_map, expiry)` per collection — you will extend it to `(raw_schema, type_map, raw_stats, expiry)` and update the two unpack sites in `_sample_schema`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_field_stats.py
import pytest

from guardmcp.plugins.mongodb.schema import build_field_stats


def test_build_field_stats_counts_and_distinct():
    docs = [{"a": "X"}, {"a": "Y"}, {"a": "X"}, {"a": None}]
    s = build_field_stats(docs, [])
    assert s["a"]["count"] == 4
    assert s["a"]["null_count"] == 1
    assert s["a"]["distinct_count"] == 2
    assert set(s["a"]["sample_values"]) == {"X", "Y"}


def test_build_field_stats_counts_absent_as_null():
    docs = [{"a": 1}, {"b": 2}]  # 'a' absent in second doc
    s = build_field_stats(docs, [])
    assert s["a"]["count"] == 2 and s["a"]["null_count"] == 1


def test_masked_field_has_no_values():
    docs = [{"password": "secret1"}, {"password": "secret2"}]
    s = build_field_stats(docs, ["password"])
    assert s["password"]["sample_values"] is None
    assert s["password"]["distinct_count"] is None


class _FakeExec:
    async def field_stats(self, collection, mask_fields):
        return {"a": {"count": 1, "null_count": 0, "distinct_count": 1, "sample_values": ["X"]}}


@pytest.mark.asyncio
async def test_plugin_field_stats_delegates():
    from guardmcp.plugins.mongodb.plugin import MongoPlugin
    plugin = MongoPlugin(executor=_FakeExec())
    out = await plugin.field_stats("user", ["password"])
    assert out["a"]["distinct_count"] == 1


@pytest.mark.asyncio
async def test_default_plugin_field_stats_empty():
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

    assert await _Bare().field_stats("user") == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest tests/unit/test_field_stats.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_field_stats'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/guardmcp/plugins/mongodb/schema.py`:

```python
_ENUM_TRACK_CAP = 50
_ENUM_VALUES_CAP = 20


def build_field_stats(raw_docs: list[dict], mask_fields: list[str]) -> dict[str, dict]:
    """Per-field sample stats from RAW sampled docs. Masking-aware: masked fields
    record NO values (distinct_count/sample_values = None). Absent fields count as
    null. Only hashable scalars (str/int/float/bool) contribute to distinct/values;
    fields with >_ENUM_TRACK_CAP distinct overflow to distinct_count=None."""
    masked = set(mask_fields)
    total = len(raw_docs)
    present: dict[str, int] = {}
    nulls: dict[str, int] = {}
    vals: dict[str, set] = {}
    overflow: dict[str, bool] = {}
    for doc in raw_docs:
        if not isinstance(doc, dict):
            continue
        for k, v in doc.items():
            present[k] = present.get(k, 0) + 1
            if v is None:
                nulls[k] = nulls.get(k, 0) + 1
                continue
            if k in masked or overflow.get(k):
                continue
            if isinstance(v, (str, int, float, bool)):
                s = vals.setdefault(k, set())
                s.add(v)
                if len(s) > _ENUM_TRACK_CAP:
                    overflow[k] = True
                    vals[k] = set()
    out: dict[str, dict] = {}
    for k in present:
        null_count = nulls.get(k, 0) + (total - present[k])
        if k in masked:
            distinct_count = None
            sample_values = None
        elif overflow.get(k):
            distinct_count = None
            sample_values = None
        else:
            s = vals.get(k, set())
            distinct_count = len(s)
            sample_values = (
                sorted(s, key=lambda x: str(x))[:_ENUM_VALUES_CAP]
                if 0 < distinct_count <= _ENUM_VALUES_CAP else None
            )
        out[k] = {
            "count": total,
            "null_count": null_count,
            "distinct_count": distinct_count,
            "sample_values": sample_values,
        }
    return out
```

In `src/guardmcp/plugins/mongodb/schema_cache.py`: import `build_field_stats` (`from .schema import apply_mask, build_type_map, infer_schema, build_field_stats`); change the cache tuple to 4 elements and compute raw stats from the same `docs`. Replace the cache-read/build/store in `_sample_schema` so it stores `(raw_schema, type_map, raw_stats, expiry)` where `raw_stats = build_field_stats(docs, [])` (mask applied at read time), and update the cached-unpack to `raw_schema, type_map, _raw_stats, expiry = cached`. Add:

```python
    async def field_stats(
        self, collection: str, mask_fields: list[str], sample_size: int | None = None
    ) -> dict[str, dict]:
        """Per-field sample stats reusing the SAME cached sample as schema
        inference (no new reads). Masking applied at read time so masked fields
        never carry values."""
        await self._sample_schema(collection, sample_size)  # ensures cache populated
        cached = self._schema_cache.get(collection)
        raw_stats = cached[2] if cached else {}
        masked = set(mask_fields)
        redacted: dict[str, dict] = {}
        for field, st in raw_stats.items():
            if field in masked:
                redacted[field] = {**st, "distinct_count": None, "sample_values": None}
            else:
                redacted[field] = dict(st)
        return redacted
```

> Note: when `schema_cache_ttl <= 0` the cache isn't stored — in that branch have `_sample_schema` still compute `raw_stats` and, for `field_stats`, recompute via a direct sample if `cached is None`. Keep it simple: if `cached is None`, re-run `_sample_schema` is a no-op for TTL<=0; instead compute stats inline by sampling once more only in the TTL-disabled path. For the default config (TTL=300) the cached path applies.

Add to `src/guardmcp/plugins/mongodb/executor.py` (near `collection_schema`):

```python
    async def field_stats(self, collection: str, mask_fields: list[str]) -> dict[str, dict]:
        return await self._schema.field_stats(collection, mask_fields)
```

Add to `src/guardmcp/core/interfaces/plugin.py` after the `relationships` default:

```python
    async def field_stats(self, resource: str, mask_fields: list[str] | None = None) -> dict:
        """Return per-field sample stats {field: {count,null_count,distinct_count,
        sample_values}}. Safe default {} so backends without sampling stay valid."""
        return {}
```

Add to `src/guardmcp/plugins/mongodb/plugin.py` after `relationships`:

```python
    async def field_stats(self, resource: str, mask_fields: list[str] | None = None) -> dict:
        if self._executor is None:
            return {}
        try:
            return await self._executor.field_stats(resource, mask_fields or [])
        except Exception:
            return {}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest tests/unit/test_field_stats.py tests/unit/test_mongo_plugin.py -v`
Expected: PASS (field_stats tests pass; existing mongo plugin tests still pass)

- [ ] **Step 5: Commit**

```bash
git add src/guardmcp/core/interfaces/plugin.py src/guardmcp/plugins/mongodb/schema.py src/guardmcp/plugins/mongodb/schema_cache.py src/guardmcp/plugins/mongodb/executor.py src/guardmcp/plugins/mongodb/plugin.py tests/unit/test_field_stats.py
git commit -m "feat(context): DatabasePlugin.field_stats seam + MongoDB masking-aware sample stats"
```

---

### Task 4: Wire semantics into `describe_collection`

**Files:**
- Modify: `src/guardmcp/core/pipeline.py` (`describe_collection`, ~L536-557)
- Test: `tests/unit/test_describe_collection_semantics.py`

**Interfaces:**
- Consumes: `FieldSemanticsAnalyzer`, `SemanticsInput`, `FieldStat` (Tasks 1-2); executor `collection_indexes`/`field_stats`, plugin `relationships`, `policy.mask_fields_for` (existing).
- Produces: `describe_collection` returns `{"fields": {...}, "semantics": {field: {...}}, "masked_fields": [...]}` (additive). Governance unchanged (still policy-gated + audited).

**Orientation:** run `graphify query "GuardPipeline describe_collection schema output"` first; else read `src/guardmcp/core/pipeline.py` around `describe_collection`. Build `SemanticsInput` from: `fields` = the schema map already returned; `indexes` = `await executor.collection_indexes(collection)` (guarded); `masked_fields` = `policy.mask_fields_for(collection)`; `field_stats` = `await plugin.field_stats(collection, masked_fields)` mapped into `FieldStat`; relationship edges + fan-in from `await plugin.relationships(allowed)` where `allowed = discover-permitted collections` (reuse the same permission filter as `discover_collections`). All new calls best-effort (try/except → empty) so `describe_collection` never regresses.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_describe_collection_semantics.py
import pytest

from guardmcp.core.pipeline import GuardPipeline


class _Executor:
    async def list_collections(self):
        return ["user", "orders"]
    async def collection_schema(self, collection, mask_fields, sample_size=None):
        return {"user": {"_id": "objectId", "email": "masked", "status": "string"},
                "orders": {"_id": "objectId", "user_id": "objectId"}}[collection]
    async def collection_indexes(self, collection):
        return []
    async def field_stats(self, collection, mask_fields):
        if collection == "user":
            return {"status": {"count": 100, "null_count": 0, "distinct_count": 2,
                               "sample_values": ["ACTIVE", "INACTIVE"]}}
        return {}


class _Plugin:
    _executor = None
    async def relationships(self, resources):
        return [{"from_resource": "orders", "from_field": "user_id", "to_resource": "user",
                 "to_field": "_id", "kind": "naming", "confidence": 0.5, "evidence": "x"}]
    async def field_stats(self, resource, mask_fields=None):
        return await _Executor().field_stats(resource, mask_fields or [])


def _pipeline():
    from guardmcp.core.policy.loader import PolicyLoader
    from guardmcp.core.policy.models import Policy, CollectionPolicy
    # Minimal pipeline with a stub policy loader + registry exposing _Plugin/_Executor.
    ex = _Executor()
    plugin = _Plugin(); plugin._executor = ex

    class _Entry: pass
    entry = _Entry(); entry.executor = ex; entry.plugin = plugin

    class _Reg:
        def get_active(self): return entry
        def get(self, n): return entry
    class _Loader:
        def get(self, agent):
            return Policy(agent=agent, collections=CollectionPolicy(allow=["*"], deny=[]),
                          mask_fields=["email"])
    from guardmcp.core.policy.engine import PolicyEngine
    from guardmcp.core.risk.engine import RiskEngine

    class _Audit:
        def build(self, **k): return k
        async def log(self, r): return None
    p = GuardPipeline(policy_loader=_Loader(), policy_engine=PolicyEngine(),
                      risk_engine=RiskEngine(), audit_logger=_Audit(), approval_store=None,
                      executor=ex, registry=_Reg())
    return p


@pytest.mark.asyncio
async def test_describe_includes_semantics_and_masked():
    p = _pipeline()
    out = await p.describe_collection("claude", "user")
    assert out["fields"]["_id"] == "objectId"
    assert out["semantics"]["_id"]["role"] == "primary_identifier"
    assert out["semantics"]["status"]["role"] == "enum_status"
    assert set(out["semantics"]["status"]["values"]) == {"ACTIVE", "INACTIVE"}
    assert out["semantics"]["email"]["role"] == "pii"
    assert "email" in out["masked_fields"]


@pytest.mark.asyncio
async def test_describe_foreign_reference():
    p = _pipeline()
    out = await p.describe_collection("claude", "orders")
    assert out["semantics"]["user_id"]["role"] == "foreign_identifier"
    assert out["semantics"]["user_id"]["references"] == "user"
```

> Before writing implementation, confirm the real `GuardPipeline.__init__` signature and `describe_collection` return shape via graphify/read; adapt the stub `_pipeline()` fixture to the actual constructor (the fields above mirror `core/pipeline.py`). Keep assertions at full strength.

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest tests/unit/test_describe_collection_semantics.py -v`
Expected: FAIL — `KeyError: 'semantics'`

- [ ] **Step 3: Write minimal implementation**

In `src/guardmcp/core/pipeline.py`, extend `describe_collection` so that after computing `schema` it assembles semantics (all new work best-effort). Replace the final `return {"fields": schema}` region with:

```python
        semantics, masked_fields = await self._field_semantics(agent, collection, schema, policy)
        result: dict[str, Any] = {"fields": schema}
        if semantics is not None:
            result["semantics"] = semantics
        result["masked_fields"] = masked_fields
        return result
```

And add a helper method to `GuardPipeline`:

```python
    async def _field_semantics(self, agent, collection, schema, policy):
        """Best-effort per-field semantics (never raises; degrades to None)."""
        from .context.models import FieldStat, SemanticsInput
        from .context.semantics import FieldSemanticsAnalyzer
        from .validation import collection_permitted

        masked_fields = list(policy.mask_fields_for(collection)) if policy is not None else []
        try:
            executor = self._get_executor()
            plugin = None
            if self._registry is not None:
                entry = self._registry.get_active()
                plugin = getattr(entry, "plugin", None) if entry is not None else None

            indexes = []
            getter = getattr(executor, "collection_indexes", None)
            if getter is not None:
                indexes = await getter(collection)

            raw_stats = {}
            if plugin is not None and hasattr(plugin, "field_stats"):
                raw_stats = await plugin.field_stats(collection, masked_fields)
            field_stats = {k: FieldStat(**v) for k, v in raw_stats.items()}

            edges, fan_in = [], {}
            if plugin is not None and hasattr(plugin, "relationships") and policy is not None:
                allowed = [
                    c for c in await executor.list_collections()
                    if collection_permitted(c, policy.collections.allow, policy.collections.deny)
                ]
                all_edges = await plugin.relationships(allowed)
                for e in all_edges:
                    if e.get("from_resource") == collection:
                        edges.append(e)
                    ff = e.get("from_field")
                    if ff:
                        fan_in.setdefault(ff, set()).add(e.get("from_resource"))
                fan_in = {k: len(v) for k, v in fan_in.items()}

            inp = SemanticsInput(
                resource=collection, fields=schema, indexes=indexes, edges=edges,
                fan_in=fan_in, field_stats=field_stats, masked_fields=masked_fields,
            )
            result = FieldSemanticsAnalyzer().analyze(inp)
            return {f: s.model_dump(exclude_none=True) for f, s in result.fields.items()}, masked_fields
        except Exception:
            return None, masked_fields
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest tests/unit/test_describe_collection_semantics.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/guardmcp/core/pipeline.py tests/unit/test_describe_collection_semantics.py
git commit -m "feat(context): attach field semantics + masked_fields to describe_collection"
```

---

### Task 5: Integration + governance + data-agnostic tests

**Files:**
- Create: `tests/integration/test_field_semantics_integration.py`

**Interfaces:**
- Consumes: everything above; a governed fake pipeline whose `discover_collections`/`describe_collection` enforce allow/deny + masking.

**Proves:** (1) the MCP collection-schema tool output carries `semantics` + `masked_fields`; (2) a masked field never carries a value/enum; (3) a denied collection yields no semantics; (4) purely-structural detection on product-neutral field names (no English tokens) — a high-fan-in FK named `grp` → tenant, a `date`-typed `xts` → timestamp, a low-cardinality string `cd` → enum.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_field_semantics_integration.py
import pytest

from guardmcp.core.context.models import FieldStat, SemanticsInput
from guardmcp.core.context.semantics import FieldSemanticsAnalyzer


def test_structural_detection_no_english_tokens():
    """Roles detected with product-neutral names — proves no name vocab is required."""
    inp = SemanticsInput(
        resource="t",
        fields={"_id": "objectId", "grp": "objectId", "xts": "date", "cd": "string"},
        edges=[{"from_field": "grp", "to_resource": "g", "confidence": 0.75}],
        fan_in={"grp": 4},
        field_stats={"cd": FieldStat(count=100, distinct_count=3, sample_values=["a", "b", "c"])},
    )
    r = FieldSemanticsAnalyzer().analyze(inp).fields
    assert r["_id"].role == "primary_identifier"
    assert r["grp"].role == "tenant_key"       # structural: fan-in only
    assert r["xts"].role == "timestamp"        # structural: date type only
    assert r["cd"].role == "enum_status"       # structural: cardinality only


def test_masked_field_never_valued_end_to_end():
    inp = SemanticsInput(resource="user", fields={"password": "masked", "st": "string"},
        masked_fields=["password"],
        field_stats={"st": FieldStat(count=10, distinct_count=1, sample_values=["A"])})
    r = FieldSemanticsAnalyzer().analyze(inp).fields
    assert r["password"].role == "pii" and r["password"].values is None
```

Add a governed describe test mirroring Task 4's fixture but asserting a **denied** collection returns no semantics (reuse the `_pipeline()` fixture pattern; set policy `deny=["secrets"]` and assert `describe_collection("claude","secrets")` is `None`).

- [ ] **Step 2: Run test to verify it fails / passes**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest tests/integration/test_field_semantics_integration.py -v`
Expected: these exercise already-built code — expect PASS. If any FAIL, fix the implicated stage (do NOT weaken the test); if a failure is a fixture-wiring mistake, correct the fixture.

- [ ] **Step 3: Run the full slice + regression suite**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest tests/unit/test_context_models.py tests/unit/test_field_semantics_analyzer.py tests/unit/test_field_stats.py tests/unit/test_describe_collection_semantics.py tests/integration/test_field_semantics_integration.py -v`
Then full regression: `/Users/suresh/guardmcp/.venv/bin/python -m pytest -q`
Expected: ALL PASS. Then `/Users/suresh/guardmcp/.venv/bin/python -m ruff check src tests`.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_field_semantics_integration.py
git commit -m "test(context): field-semantics integration, governance, data-agnostic proof"
```

---

## Self-Review

**Spec coverage:** Core-6 roles (T2), structural-first + generic boosters (T2), plugin field_stats seam + safe default (T3), reuse existing sample / no new reads (T3), masking-aware stats + pii-by-name (T2/T3), relationship-graph reuse for foreign/tenant + fan-in (T4), additive schema output `semantics`+`masked_fields` (T4), governance (denied→none, masked→no values) (T4/T5), data-agnostic proof with product-neutral names (T2/T5), determinism (T2), backward-compat default+additive (T3/T4). Deferred by spec (not this plan): entity map, data-trust signals, unified context bundle.

**Placeholders:** none — every step has real code. Two steps instruct reading an existing file first (schema_cache cache-tuple; describe_collection/GuardPipeline ctor) because exact surrounding lines must be matched; the change itself is fully specified.

**Type consistency:** `FieldStat`/`FieldSemantics`/`SemanticsInput`/`SemanticsResult` fields consistent T1↔T2↔T4↔T5. `field_stats` dict shape `{count,null_count,distinct_count,sample_values}` consistent schema↔cache↔executor↔plugin↔analyzer-input. `edges` dict keys `from_field/to_resource/confidence/from_resource` consistent with the shipped `relationships()` output. Role string constants shared from `context.models`.
