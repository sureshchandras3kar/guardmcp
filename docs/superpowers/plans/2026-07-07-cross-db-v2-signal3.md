# Cross-Database Relationships v2 — Signal 3 (Identifier-Role Alignment) Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add identifier-role alignment to cross-DB join-key discovery: (A) boost v1 shared-name/value-overlap edges when endpoint roles align, and (B) discover NEW cross-DB links from `foreign_identifier.references → another DB's primary_identifier` (even when field names differ), using the field-semantics roles now on `describe_collection`.

**Architecture:** Extend `core/planning/cross_db.py` (matcher: `_matches_resource`, `align_by_identifier_role` for B, `boost_by_roles` for A, `merge_edges` dedupe) and `core/planning/cross_db_resolver.py` (gather `semantics_by_loc` from `describe_collection`, run v1 + A + B, merge). `guardmcp_relationships` already emits `cross_db_edges` — no tool change.

**Tech Stack:** Python 3.12+, Pydantic v2, pytest/pytest-asyncio.

## Global Constraints

- Deterministic, NO LLM, data-agnostic: NO hardcoded product/field/collection names; alignment driven by roles + the id-name resource convention (exact/singular/plural). Value evidence from live bounded samples.
- Governance: span only `databases_allow`; masked fields (role `pii`, or in `masked_fields`) NEVER participate in alignment; roles read via the governed `describe_collection`; value sampling via `sample_field_values` (bounded).
- `kind="identifier_alignment"` is a new string value for `CrossDbEdge.kind` (no schema change).
- Back-compat: no semantics/roles → no signal-3 edges; v1 shared-name/value-overlap output unchanged; additive. Dedup keeps the higher-confidence edge per endpoint pair.
- Run tests via `/Users/suresh/guardmcp/.venv/bin/python -m pytest <path> -v`. FULL regression each task: `... -m pytest -q --deselect tests/integration/test_transport_lifecycle.py::test_streamable_http_db_tool_survives_session_boundary`. Eval: `... -m guardmcp.eval evals/cases/` (42/42). Lint: `... -m ruff check src tests`. (No `python` on PATH.) `git status` clean at each gate.
- Codebase-orientation: run `graphify query "<question>"` before reading a source file; if unavailable in-shell, read directly. Applies to subagents.
- Commit bodies end with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

## Constants (in cross_db.py)

- Existing: `_ID_NAME_RE`, `OVERLAP_MIN = 0.3`, `SAMPLE_CAP = 100`.
- New: `ALIGN_BASE = 0.75` (reference-alignment base confidence); `ROLE_BOOST = 0.15` (added to a v1 edge on role alignment); `CONF_CAP = 0.95`.
- Role strings (match field-semantics): `"primary_identifier"`, `"foreign_identifier"`, `"tenant_key"`, `"pii"`.

---

### Task 1: Matcher signal-3 (`core/planning/cross_db.py`)

**Files:**
- Modify: `src/guardmcp/core/planning/cross_db.py`
- Test: `tests/unit/test_cross_db_signal3.py`

**Interfaces:**
- Consumes: `CrossDbEdge`, `CrossDbEndpoint` (models); existing `match_cross_db` output.
- Produces:
  - `_matches_resource(target: str, collection: str) -> bool` — case-insensitive exact / singular / plural (`t == c`, `t+"s" == c`, `t == c.rstrip("s")`).
  - `align_by_identifier_role(semantics_by_loc: dict[tuple[str,str], dict[str,dict]], sample_values) -> list[CrossDbEdge]` — capability B. `semantics_by_loc[(db,coll)][field] = {"role":..., "references":...}`. For each `foreign_identifier` field `f` (role) with `references=R` in `(dbA,collA)`: for each `(dbB,collB)` with `dbB != dbA` and `_matches_resource(R, collB)` that has a `primary_identifier` field `pk` (prefer `"_id"`): base conf `ALIGN_BASE`; value-overlap boost via `sample_values(dbA,collA,f)` vs `sample_values(dbB,collB,pk)` → `ratio`, `conf = round(min(CONF_CAP, ALIGN_BASE + 0.2*ratio), 4)`, `overlap_ratio=ratio`; emit `CrossDbEdge(from=dbA.collA.f, to=dbB.collB.pk, kind="identifier_alignment", confidence, overlap_ratio, evidence)`. Deterministic order.
  - `boost_by_roles(edges: list[CrossDbEdge], semantics_by_loc) -> list[CrossDbEdge]` — capability A. For each v1 edge, look up the role of the `from` and `to` endpoints in `semantics_by_loc`; if aligned — one `foreign_identifier` & the other `primary_identifier`, OR both `tenant_key` — return an upgraded copy with `kind="identifier_alignment"`, `confidence=round(min(CONF_CAP, edge.confidence + ROLE_BOOST), 4)`, evidence appended; else keep the edge unchanged.
  - `merge_edges(*edge_lists) -> list[CrossDbEdge]` — concatenate + dedupe by the UNORDERED endpoint pair (`frozenset` of `(database,collection,field)` tuples), keeping the higher `confidence` (tie → prefer `kind="identifier_alignment"`). Deterministic order.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_cross_db_signal3.py
import pytest

from guardmcp.core.planning.cross_db import (
    align_by_identifier_role, boost_by_roles, merge_edges, _matches_resource,
)
from guardmcp.core.planning.models import CrossDbEdge, CrossDbEndpoint


def test_matches_resource_singular_plural():
    assert _matches_resource("account", "accounts")
    assert _matches_resource("Accounts", "account")
    assert _matches_resource("user", "user")
    assert not _matches_resource("user", "orders")


@pytest.mark.asyncio
async def test_reference_alignment_links_foreign_to_primary_diff_names():
    sem = {
        ("identity", "user"): {"acct_ref": {"role": "foreign_identifier", "references": "accounts"}},
        ("billing", "accounts"): {"_id": {"role": "primary_identifier", "references": None}},
    }
    values = {("identity", "user", "acct_ref"): ["a", "b", "c"],
              ("billing", "accounts", "_id"): ["b", "c", "d"]}
    async def sampler(db, coll, field): return values.get((db, coll, field), [])
    edges = await align_by_identifier_role(sem, sampler)
    assert len(edges) == 1
    e = edges[0]
    assert e.kind == "identifier_alignment"
    assert (e.from_.database, e.from_.collection, e.from_.field) == ("identity", "user", "acct_ref")
    assert (e.to.database, e.to.collection, e.to.field) == ("billing", "accounts", "_id")
    assert e.confidence > 0.75  # value-overlap boosted (ratio 2/3)


@pytest.mark.asyncio
async def test_reference_alignment_needs_different_databases():
    sem = {
        ("identity", "user"): {"acct_id": {"role": "foreign_identifier", "references": "account"}},
        ("identity", "account"): {"_id": {"role": "primary_identifier", "references": None}},
    }
    async def sampler(db, coll, field): return []
    assert await align_by_identifier_role(sem, sampler) == []  # same db -> not cross-db


@pytest.mark.asyncio
async def test_masked_or_non_identifier_never_aligns():
    sem = {
        ("a", "c1"): {"secret": {"role": "pii", "references": "accounts"}},
        ("b", "accounts"): {"_id": {"role": "primary_identifier", "references": None}},
    }
    async def sampler(db, coll, field): return []
    assert await align_by_identifier_role(sem, sampler) == []  # pii role not foreign_identifier


def test_boost_by_roles_upgrades_aligned_v1_edge():
    edge = CrossDbEdge(
        **{"from": CrossDbEndpoint(database="a", collection="user", field="account_id")},
        to=CrossDbEndpoint(database="b", collection="accounts", field="account_id"),
        kind="value_overlap", confidence=0.7, overlap_ratio=0.5, evidence="v1",
    )
    sem = {
        ("a", "user"): {"account_id": {"role": "foreign_identifier", "references": "accounts"}},
        ("b", "accounts"): {"account_id": {"role": "primary_identifier", "references": None}},
    }
    out = boost_by_roles([edge], sem)
    assert out[0].kind == "identifier_alignment" and out[0].confidence == pytest.approx(0.85)


def test_boost_leaves_unaligned_edge_unchanged():
    edge = CrossDbEdge(
        **{"from": CrossDbEndpoint(database="a", collection="x", field="k_id")},
        to=CrossDbEndpoint(database="b", collection="y", field="k_id"),
        kind="shared_name", confidence=0.5, overlap_ratio=0.0, evidence="v1",
    )
    out = boost_by_roles([edge], {})  # no roles known
    assert out[0].kind == "shared_name" and out[0].confidence == 0.5


def test_merge_dedupes_keeping_higher_confidence():
    lo = CrossDbEdge(**{"from": CrossDbEndpoint(database="a", collection="u", field="acct_id")},
                     to=CrossDbEndpoint(database="b", collection="accounts", field="_id"),
                     kind="shared_name", confidence=0.5, evidence="lo")
    hi = CrossDbEdge(**{"from": CrossDbEndpoint(database="b", collection="accounts", field="_id")},
                     to=CrossDbEndpoint(database="a", collection="u", field="acct_id"),
                     kind="identifier_alignment", confidence=0.9, evidence="hi")
    merged = merge_edges([lo], [hi])
    assert len(merged) == 1 and merged[0].confidence == 0.9  # unordered pair dedup, higher wins
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest tests/unit/test_cross_db_signal3.py -v`
Expected: FAIL — `ImportError: cannot import name 'align_by_identifier_role'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/guardmcp/core/planning/cross_db.py` (keep existing code; add new constants + functions):

```python
ALIGN_BASE = 0.75
ROLE_BOOST = 0.15
CONF_CAP = 0.95
_ROLE_PRIMARY = "primary_identifier"
_ROLE_FOREIGN = "foreign_identifier"
_ROLE_TENANT = "tenant_key"


def _matches_resource(target: str, collection: str) -> bool:
    t, c = target.lower(), collection.lower()
    return t == c or (t + "s") == c or t == c.rstrip("s")


def _primary_field(loc_sem: dict[str, dict]) -> str | None:
    """The primary_identifier field of a collection (prefer '_id')."""
    prims = [f for f, s in loc_sem.items() if s.get("role") == _ROLE_PRIMARY]
    if not prims:
        return None
    return "_id" if "_id" in prims else sorted(prims)[0]


def _endpoint_role(semantics_by_loc, database, collection, field) -> str | None:
    return (semantics_by_loc.get((database, collection), {}).get(field) or {}).get("role")


async def align_by_identifier_role(
    semantics_by_loc: dict[tuple[str, str], dict[str, dict]],
    sample_values: Callable[[str, str, str], Awaitable[list]],
) -> list[CrossDbEdge]:
    """Capability B: foreign_identifier.references -> another DB's primary_identifier."""
    edges: list[CrossDbEdge] = []
    fks: list[tuple[str, str, str, str]] = []  # (dbA, collA, field, references)
    for (dba, ca), fields in semantics_by_loc.items():
        for f, s in fields.items():
            if s.get("role") == _ROLE_FOREIGN and s.get("references"):
                fks.append((dba, ca, f, s["references"]))
    fks.sort()
    targets = sorted(semantics_by_loc.keys())
    for dba, ca, f, ref in fks:
        for (dbb, cb) in targets:
            if dbb == dba or not _matches_resource(ref, cb):
                continue
            pk = _primary_field(semantics_by_loc[(dbb, cb)])
            if pk is None:
                continue
            va = set(await sample_values(dba, ca, f))
            vb = set(await sample_values(dbb, cb, pk))
            denom = min(len(va), len(vb))
            ratio = (len(va & vb) / denom) if denom else 0.0
            conf = round(min(CONF_CAP, ALIGN_BASE + 0.2 * ratio), 4)
            edges.append(
                CrossDbEdge(
                    **{"from": CrossDbEndpoint(database=dba, collection=ca, field=f)},
                    to=CrossDbEndpoint(database=dbb, collection=cb, field=pk),
                    kind="identifier_alignment", confidence=conf, overlap_ratio=ratio,
                    evidence=(
                        f"foreign_identifier '{ca}.{f}' references '{ref}' -> "
                        f"primary key '{dbb}.{cb}.{pk}' (value overlap {ratio:.2f})"
                    ),
                )
            )
    return edges


def boost_by_roles(
    edges: list[CrossDbEdge],
    semantics_by_loc: dict[tuple[str, str], dict[str, dict]],
) -> list[CrossDbEdge]:
    """Capability A: upgrade a v1 edge whose endpoint roles align."""
    out: list[CrossDbEdge] = []
    for e in edges:
        ra = _endpoint_role(semantics_by_loc, e.from_.database, e.from_.collection, e.from_.field)
        rb = _endpoint_role(semantics_by_loc, e.to.database, e.to.collection, e.to.field)
        pair = {ra, rb}
        aligned = ({_ROLE_FOREIGN, _ROLE_PRIMARY} == pair) or (ra == _ROLE_TENANT and rb == _ROLE_TENANT)
        if aligned:
            out.append(
                e.model_copy(update={
                    "kind": "identifier_alignment",
                    "confidence": round(min(CONF_CAP, e.confidence + ROLE_BOOST), 4),
                    "evidence": e.evidence + f"; role-aligned ({ra}/{rb})",
                })
            )
        else:
            out.append(e)
    return out


def merge_edges(*edge_lists: list[CrossDbEdge]) -> list[CrossDbEdge]:
    """Concatenate + dedupe by UNORDERED endpoint pair, keeping higher confidence
    (tie → prefer identifier_alignment). Deterministic order."""
    best: dict[frozenset, CrossDbEdge] = {}
    for lst in edge_lists:
        for e in lst:
            key = frozenset({
                (e.from_.database, e.from_.collection, e.from_.field),
                (e.to.database, e.to.collection, e.to.field),
            })
            cur = best.get(key)
            if cur is None:
                best[key] = e
            elif e.confidence > cur.confidence or (
                e.confidence == cur.confidence
                and e.kind == "identifier_alignment" != cur.kind
            ):
                best[key] = e
    return sorted(
        best.values(),
        key=lambda e: (e.from_.database, e.from_.collection, e.from_.field,
                       e.to.database, e.to.collection, e.to.field),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest tests/unit/test_cross_db_signal3.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add src/guardmcp/core/planning/cross_db.py tests/unit/test_cross_db_signal3.py
git commit -m "feat(context): cross-db signal-3 matcher (identifier-role alignment + role boost)"
```

---

### Task 2: Resolver wires signal-3 (`core/planning/cross_db_resolver.py`)

**Files:**
- Modify: `src/guardmcp/core/planning/cross_db_resolver.py`
- Test: `tests/unit/test_cross_db_resolver_signal3.py`

**Interfaces:**
- Consumes: `match_cross_db` (v1), `align_by_identifier_role`, `boost_by_roles`, `merge_edges`, `SAMPLE_CAP` (Task 1); `describe_collection` returning `{"fields":..., "semantics": {field: {role, references, ...}}, "masked_fields":[...]}`.
- Produces: `CrossDatabaseResolver.edges(agent, databases)` now also builds
  `semantics_by_loc: dict[(db,coll), dict[field, {"role","references"}]]` from the
  `semantics` block (EXCLUDING masked fields), then returns
  `merge_edges(boost_by_roles(v1_edges, semantics_by_loc), align_by_identifier_role(semantics_by_loc, sampler))`.

**Orientation:** run `graphify query "CrossDatabaseResolver edges describe_collection semantics"`; else read `cross_db_resolver.py` (current body is short — the `edges` method builds `inventory` + `sampler` + returns `match_cross_db`).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_cross_db_resolver_signal3.py
import pytest

from guardmcp.core.planning.cross_db_resolver import CrossDatabaseResolver


class _Guard:
    async def discover_collections(self, agent, database=None):
        return {"identity": ["user"], "billing": ["accounts"]}.get(database, [])
    async def describe_collection(self, agent, collection, database=None):
        return {
            ("identity", "user"): {
                "fields": {"_id": "objectId", "acct_ref": "string", "email": "masked"},
                "semantics": {
                    "acct_ref": {"role": "foreign_identifier", "references": "accounts"},
                    "email": {"role": "pii"},
                },
                "masked_fields": ["email"],
            },
            ("billing", "accounts"): {
                "fields": {"_id": "objectId"},
                "semantics": {"_id": {"role": "primary_identifier"}},
                "masked_fields": [],
            },
        }.get((database, collection))


class _Plugin:
    async def sample_field_values(self, collection, field, database=None, cap=100):
        return {("identity", "acct_ref"): ["a", "b"], ("billing", "_id"): ["b", "c"]}.get(
            (database, field), [])


@pytest.mark.asyncio
async def test_resolver_emits_identifier_alignment_edge():
    r = CrossDatabaseResolver(_Guard(), lambda: _Plugin())
    edges = await r.edges("claude", ["identity", "billing"])
    align = [e for e in edges if e.kind == "identifier_alignment"]
    assert align, "expected an identifier_alignment edge from acct_ref -> accounts._id"
    e = align[0]
    assert (e.from_.collection, e.from_.field) == ("user", "acct_ref")
    assert (e.to.collection, e.to.field) == ("accounts", "_id")


@pytest.mark.asyncio
async def test_masked_field_never_in_signal3_edges():
    r = CrossDatabaseResolver(_Guard(), lambda: _Plugin())
    edges = await r.edges("claude", ["identity", "billing"])
    assert all(e.from_.field != "email" and e.to.field != "email" for e in edges)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest tests/unit/test_cross_db_resolver_signal3.py -v`
Expected: FAIL — no `identifier_alignment` edge (signal-3 not wired).

- [ ] **Step 3: Write minimal implementation**

In `cross_db_resolver.py`, update imports and `edges`:

```python
from .cross_db import (
    SAMPLE_CAP, align_by_identifier_role, boost_by_roles, match_cross_db, merge_edges,
)
```

In `edges`, while iterating collections, also build `semantics_by_loc` (exclude masked fields):

```python
        inventory: dict[tuple[str, str], set[str]] = {}
        semantics_by_loc: dict[tuple[str, str], dict[str, dict]] = {}
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
                if not desc:
                    continue
                fields = desc.get("fields", {})
                names = {f for f, t in fields.items() if t != "masked"}
                if names:
                    inventory[(db, col)] = names
                masked = set(desc.get("masked_fields", []))
                sem = desc.get("semantics", {})
                loc_sem = {
                    f: {"role": s.get("role"), "references": s.get("references")}
                    for f, s in sem.items()
                    if f not in masked and s.get("role") != "pii"
                }
                if loc_sem:
                    semantics_by_loc[(db, col)] = loc_sem
```

(Keep the existing `sampler` closure.) Replace the final return with:

```python
        v1 = await match_cross_db(inventory, sampler)
        boosted = boost_by_roles(v1, semantics_by_loc)
        aligned = await align_by_identifier_role(semantics_by_loc, sampler)
        return merge_edges(boosted, aligned)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest tests/unit/test_cross_db_resolver_signal3.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/guardmcp/core/planning/cross_db_resolver.py tests/unit/test_cross_db_resolver_signal3.py
git commit -m "feat(context): resolver wires cross-db signal-3 (semantics roles + merge)"
```

---

### Task 3: Integration + governance + data-agnostic + back-compat

**Files:**
- Create: `tests/integration/test_cross_db_signal3_integration.py`

**Interfaces:**
- Consumes: `guardmcp_relationships` tool (already emits `cross_db_edges`); `CrossDatabaseResolver`.

**Proves:** (1) end-to-end via `guardmcp_relationships`: an `identifier_alignment` cross-DB edge appears for a reference-based link across two seeded databases; (2) role-boost upgrades a shared-name edge whose endpoints are role-aligned; (3) a masked/pii field never appears in any signal-3 edge; (4) data-agnostic: product-neutral names (`grp_ref`→`grps._id`) align by role, not by English tokens; (5) back-compat: describe_collection with NO `semantics` (roles absent) → only v1 edges, unchanged; full regression + eval 42/42.

- [ ] **Step 1: Write the tests**

Mirror the Task-2 resolver harness + the v1 `guardmcp_relationships` tool test (`tests/unit/test_relationships_cross_db_tool.py`) for the end-to-end assertion. Assert real values: the `identifier_alignment` edge endpoints + kind; role-boosted confidence > the v1 base; masked field absent; product-neutral alignment; and a no-`semantics` fixture yields no `identifier_alignment` edges (only `shared_name`/`value_overlap`).

- [ ] **Step 2: Run + full regression + eval**

Run: `/Users/suresh/guardmcp/.venv/bin/python -m pytest tests/integration/test_cross_db_signal3_integration.py -v`
Then `git status` (clean), FULL regression (`--deselect` the transport flake), eval (42/42), ruff. Expected: ALL PASS. If a real bug surfaces, fix the implicated task (don't weaken the test).

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_cross_db_signal3_integration.py
git commit -m "test(context): cross-db signal-3 integration + governance + data-agnostic + back-compat"
```

---

## Self-Review

**Spec coverage:** matcher B (`align_by_identifier_role`) + A (`boost_by_roles`) + dedupe (`merge_edges`) + `_matches_resource` (T1); resolver gathers semantics (masked/pii excluded) + runs v1→boost→align→merge (T2); integration/governance/data-agnostic/back-compat (T3). `kind="identifier_alignment"` (no schema change). Tool unchanged (already emits cross_db_edges). Transitive path composition explicitly out of scope.

**Placeholders:** none — T1/T2 have complete code; T3 gives the proof list + harness references (mirror existing cross-db + relationships-tool tests).

**Type consistency:** `semantics_by_loc: dict[(database,collection), dict[field, {"role","references"}]]` consistent T1↔T2; `align_by_identifier_role(semantics_by_loc, sample_values)`, `boost_by_roles(edges, semantics_by_loc)`, `merge_edges(*lists)` signatures consistent; `CrossDbEdge`/`CrossDbEndpoint` (`from_`↔`"from"` alias) reused; role strings match field-semantics (`primary_identifier`/`foreign_identifier`/`tenant_key`/`pii`).
