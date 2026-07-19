# Field Semantics — Design (Context Engine, Slice 1)

Date: 2026-07-02
Status: Approved (design)
Pillar: Context Engine (Option 3) — pre-execution database *understanding*

## Why this exists

GuardMCP's second pillar: tell the AI things a read-only official MCP structurally
cannot — before execution. Slice 1 answers "what does each field mean?": which
field is the primary key, which is a foreign key (and to what), which is the
tenant/scope key, which are timestamps, which are enum/status fields, which are
PII. This feeds sharper ambiguity detection, entity clustering (next slice), and
the future unified context bundle.

## Non-negotiable principle: discovered, never baked in

Everything is **discovered at runtime from the connected database** — schema,
indexes, a bounded live sample, and the relationship graph. The engine works on
*any* database.

- **No hardcoded collection or field names.** No product-specific tokens
  (verified: `grep -riE "master_account|corestack|executive_dashboard" src/`
  returns zero). Detection is **structural-first**; generic English name tokens
  (e.g. `status`, `created_at`, `tenant`) are only confidence *boosters*, never
  required, and only ever fire when the connected schema actually has such a
  field.
- **Enum values come from the live sample**, never a fixed list.
- **Relationships come from live naming/index/graph**, never a fixed map.
- If the generic hints match nothing on a given DB, the engine simply returns
  fewer/lower-confidence signals — it never fabricates.

## Roles (Core 6)

Per field: one **primary role** (priority-ordered) plus an optional `pii` flag.

`primary_identifier` · `foreign_identifier` · `tenant_key` · `timestamp` ·
`enum_status` · `pii` · (`none`)

## Architecture

New Context-Engine home, database-agnostic:

```
src/guardmcp/core/context/
    __init__.py
    models.py       # FieldStat, FieldSemantics, SemanticsInput, SemanticsResult
    semantics.py    # FieldSemanticsAnalyzer — pure, deterministic, no I/O
```

- **`FieldSemanticsAnalyzer`** consumes only normalized inputs and returns
  per-field semantics. It has zero Mongo/SQL knowledge and performs no I/O:
  - `analyze(inp: SemanticsInput) -> SemanticsResult`
  - `SemanticsInput`: `resource: str`, `fields: dict[str,str]` (name→type),
    `indexes: list[dict]`, `edges: list[Relationship]` (relationship-graph edges
    where `from_resource == resource`, plus a `fan_in: dict[field,int]` count of
    how many collections reference the same target/field name — the tenant
    signal), `field_stats: dict[str, FieldStat]`, `masked_fields: list[str]`.
  - `FieldStat`: `count: int`, `null_count: int`, `distinct_count: int`,
    `sample_values: list | None` (capped; only for low-cardinality, non-PII fields).
  - `SemanticsResult`: `{field: FieldSemantics}` where `FieldSemantics` =
    `role`, `confidence: float`, `evidence: str`, `references: str | None`
    (foreign target), `values: list | None` (enum set).

- **Plugin seam:** `DatabasePlugin.field_stats(resource) -> dict` with safe
  default `{}` (SQL/other plugins unaffected — same additive pattern as
  `relationships()`). MongoDB implements it by **augmenting
  `MongoSchemaCache._sample_schema`** to derive per-field stats
  (count/null/distinct/sample-values) from the **same `docs`** it already samples,
  cached alongside the type map. **No new database reads.**

- **Reuse:** the analyzer is consumed by (a) the schema-tool output now, (b) the
  planner's ambiguity stage later, (c) the unified context bundle (future slice).

## Classification algorithm (deterministic, structural-first, no LLM)

Priority order; each rule yields confidence + `evidence`. Generic name tokens are
boosters (+), never required.

1. `primary_identifier`: `_id` → 1.0. Else a **single-field unique index** whose
   `distinct_count ≈ count` (near-unique in sample) → high; + id-like name booster.
2. `foreign_identifier`: field is the `from_field` of a relationship-graph edge
   → `references = edge.to_resource`, confidence = edge confidence. (Reuses the
   shipped graph directly.)
3. `tenant_key`: **structural** — a foreign-identifier field with high **fan-in**
   (referenced across many collections) → tenant/scope key; confidence scales
   with fan-in. + generic scope-token name booster (`tenant`/`account`/`org`/
   `customer`/`workspace`). **No product-specific names.**
4. `timestamp`: BSON `date`/`datetime` type → high. + name booster (`*_at`,
   `*_time`, `created`, `updated`).
5. `enum_status`: `string` type + **low distinct-count** relative to count (from
   sample) → emits observed `values` (capped). + status-ish name booster.
6. `pii`: name matches generic PII patterns (email/ssn/phone/card/secret/token/
   password) → flag (may co-exist with another primary role).
7. else `none`.

Thresholds (fixed constants, documented): near-unique ratio, enum max-distinct,
fan-in minimum. Deterministic given a sample; sample is bounded + cached (TTL).

## Output & exposure (additive, backward-compatible)

Extend the collection-schema output. Existing `fields` map is **unchanged**; add
parallel blocks:

```json
{
  "fields": { "user_id": "objectId", "status": "string", "created_at": "date" },
  "semantics": {
    "user_id":   {"role":"foreign_identifier","references":"user","confidence":0.75,"evidence":"FK edge to 'user' (indexed naming match)"},
    "status":    {"role":"enum_status","values":["ACTIVE","INACTIVE"],"confidence":0.7,"evidence":"low-cardinality string (2 distinct in sample)"},
    "created_at":{"role":"timestamp","confidence":0.9,"evidence":"BSON date type"}
  },
  "masked_fields": ["password","email"]
}
```

Wired via `GuardPipeline.describe_collection` (or a sibling) so the MCP
schema tools (`mongodb_collection_schema` / `db_schema`) carry it. Additive keys
= no breaking change to existing consumers.

## Governance

- The analyzer only ever sees the **masked** schema + **masked** sample: masked
  fields are already stripped/redacted by the governed accessors, so their values
  are never read or classified.
- Policy-masked fields are surfaced **by name only** in `masked_fields[]` (the
  model knows they exist; never their values or roles beyond "masked/PII").
- Denied collections → the governed accessor returns nothing → no semantics.
- No new connection, credential, or execution path. No query is executed;
  `field_stats` reuses the existing bounded sample.

## Performance

- Zero extra database reads: stats derived from the sample `describe_collection`
  already draws; cached with the schema (same TTL/LRU).
- Analyzer is pure CPU over a bounded sample + metadata — sub-millisecond.
- Fan-in is computed once from the already-built relationship graph.

## Testing

- **Unit (pure analyzer, fixtures):** `_id`→primary; unique-index+near-unique→
  primary; `user_id`+edge→foreign(references=user); high fan-in field→tenant
  (with a non-English name, to prove structural detection); `date` field→
  timestamp; low-distinct string→enum with values; email/ssn→pii; unknown→none;
  determinism (same input→same output).
- **Data-agnostic proof:** a fixture with **non-English, product-neutral** field
  names (e.g. `xref`, `grp`) where roles are detected purely structurally
  (unique index, fan-in, date type, low cardinality) — asserts name vocab is not
  required.
- **Integration:** schema tool output includes `semantics` + `masked_fields`;
  masked field never appears with a value; denied collection returns nothing;
  governance parity.
- Reuse the `evals/` harness for a first-query-correctness signal later.

## Backward compatibility

- `DatabasePlugin.field_stats` default `{}` — existing/third-party plugins valid
  unchanged.
- Schema output is additive (`semantics`, `masked_fields` keys) — existing
  consumers unaffected.

## Scope

Slice 1 of the Context Engine. Out of scope (later slices): entity map (clusters
the relationship graph into business entities; depends on this slice), data-trust
signals (nullability/freshness/distribution), and the unified `guardmcp_context`
bundle that ties all slices into one pre-flight call.
