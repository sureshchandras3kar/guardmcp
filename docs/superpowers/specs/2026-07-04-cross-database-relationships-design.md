# Cross-Database Relationships (v1) — Design

Date: 2026-07-04
Status: Approved (design)
Branch: `feat/cross-db-relationships` (off the context-engine branch, after multi-DB Phases 1–3)

## Goal

Tell an AI client which fields join collections **across different databases** on
one connection — the join keys for multi-DB (multi-hop) workflows (e.g.
identity → inventory → cost). Deterministic, no LLM, data-agnostic. Extends the
existing single-database relationship discovery (from the query planner) to span
the databases the agent is allowed to see.

## Why

MongoDB can't join across databases, so Claude chains per-DB calls. Without this,
Claude guesses which field in DB-A corresponds to which field in DB-B. This
computes those correspondences from metadata so it doesn't guess.

## Matcher (deterministic, two signals)

1. **Candidate discovery (shared identifier-name across DBs).** For each
   `(database, collection)` the agent may access, collect NON-masked field names
   (via the governed, database-scoped `describe_collection`). Build
   `field_name → [(database, collection)]`. A candidate cross-DB link is an
   **identifier-shaped** field name (`_id`, `*_id`, `*Id`) present in **≥2
   different databases**. (Restricting to id-shaped names avoids noise from
   generic fields like `name`/`status`; join keys are id-shaped.) → emit a
   `shared_name` edge, confidence ≈ 0.5.

2. **Value-overlap confirmation (bounded sampling).** For each candidate, sample
   distinct values on each side (bounded cap) and compute
   `overlap_ratio = |A ∩ B| / min(|A|, |B|)` (guarding empty/zero sides). High
   overlap → upgrade `kind="value_overlap"`, confidence 0.6–0.9 scaled by ratio;
   ~0 overlap → drop (or keep a low-confidence `shared_name`). Sampling runs ONLY
   on already-pruned candidates (name-match first, then sample) → bounded cost.

No hardcoded collection/field/product names; only the universal id-name
convention + value evidence.

## Architecture (reuses the planning relationship graph)

- **`CrossDatabaseResolver`** (new, core, database-agnostic): gathers per-database
  non-masked field inventories for the allowed `(database, collection)` set, runs
  the matcher, returns cross-DB edges. Lives alongside the existing single-DB
  `RelationshipResolver` (`core/planning/`).
- **Plugin seam:** `DatabasePlugin.sample_field_values(collection, field,
  database=None, cap=...) -> list` with a safe default `[]` (other plugins
  unaffected). MongoDB implements it as a bounded distinct-value sample of a
  single non-masked field, database-routed via `get_collection(collection,
  database)` (Phase 2). Masked fields are never sampled.
- **Models** (`core/planning/models.py` or a sibling): `CrossDbEndpoint(database,
  collection, field)`, `CrossDbEdge(from_: CrossDbEndpoint, to: CrossDbEndpoint,
  kind: "shared_name"|"value_overlap", confidence: float, overlap_ratio:
  float|None, evidence: str)`.

## Exposure — extend `guardmcp_relationships`

`guardmcp_relationships` today returns a single-database `RelationshipGraph`.
Extend it to:
- Gather the agent's allowed databases (`databases_allow` filtered like
  `list_databases`); for each, keep the existing within-DB edges (tag nodes with
  their database).
- Add a `cross_db_edges: [CrossDbEdge]` section computed by
  `CrossDatabaseResolver`.
Output stays the existing envelope; `cross_db_edges` is ADDITIVE (empty for
single-DB / no `databases_allow`).

## Governance

- Spans only databases in `databases_allow`; only NON-masked fields participate
  (masked fields excluded from the inventory AND never value-sampled).
- Edges whose either endpoint is a denied database / collection / masked field
  are dropped — the single-DB resolver's allowed-set filter, extended to
  `(database, collection, field)`.
- Value-overlap sampling is bounded + cached; reuses the governed database-routed
  read path (Phase 2). No new connection/credential surface.

## Performance

- Prune by name FIRST (cheap, metadata-only), sample SECOND (only candidates).
- Field inventory comes from the schema sample (cached). Sampled value sets
  cached per `(database, collection, field)` with the schema TTL.
- Cross-DB matching is O(candidate fields), not O(all fields).

## Back-compat

- Single-DB deployments / no `databases_allow` → no cross-DB edges; existing
  `guardmcp_relationships` output unchanged apart from an additive (empty)
  `cross_db_edges` key. `sample_field_values` default `[]` keeps other plugins
  valid. All additive.

## Testing

- Matcher unit: id-shaped field shared across 2 databases → candidate; value
  overlap upgrades confidence + sets `kind=value_overlap`; zero overlap → dropped
  / low confidence; a masked field never becomes a candidate or gets sampled; an
  endpoint in a denied database is dropped.
- Data-agnostic proof: product-neutral field names (`grp_id`, `xref_id`) matched
  purely structurally + by value overlap.
- Integration: `guardmcp_relationships` returns `cross_db_edges` linking two
  seeded databases on a shared id field with overlapping values.
- Back-compat: single-DB / no `databases_allow` → `cross_db_edges` empty, within-
  DB edges unchanged; full regression + eval (42/42).

## Out of scope (later)

- Signal 3: identifier-role alignment (primary-id ↔ foreign-id) — needs the
  field-semantics slice (parked). v1 uses shared-name + value-overlap only.
- Auto-executing the cross-DB join (GuardMCP only *tells*; the AI orchestrates).
- Transitive multi-hop path suggestion (identity→inventory→cost as one path) —
  v1 returns pairwise edges; the model composes the path.
