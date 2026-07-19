# Cross-Database Relationships v2 — Signal 3 (Identifier-Role Alignment) Design

Date: 2026-07-07
Status: Approved (design)
Branch: `feat/cross-db-v2-signal3` (off context-engine branch; field-semantics merged)

## Goal

Upgrade cross-database join-key discovery with a third signal: **identifier-role
alignment**, using the field-semantics roles (now produced by
`describe_collection`). Turns weak "shared name + value overlap" guesses into
strong, role-justified join keys — including links whose field NAMES differ.

## Inputs now available

`describe_collection(agent, collection, database)` returns (field-semantics
slice): `{"fields": {...}, "semantics": {field: {role, confidence, evidence,
references?, values?, pii}}, "masked_fields": [...]}`. Roles:
`primary_identifier`, `foreign_identifier` (with `references=<resource>`),
`tenant_key`, `timestamp`, `enum_status`, `pii`, `none`.

## Two capabilities

**A. Role-boost existing edges.** For each v1 cross-DB edge (shared-name /
value-overlap), if the endpoints' roles align — one `foreign_identifier` and the
other `primary_identifier`, or both `tenant_key` — upgrade `kind` to
`identifier_alignment` and raise confidence.

**B. Reference-based discovery (the v2 power).** For each `foreign_identifier`
field `f` in `(dbA, collA)` with `references=R`, find a collection in a DIFFERENT
database `dbB` whose name matches `R` (exact / singular / plural, reusing the
id-convention resource matcher) and that has a `primary_identifier` field `pk`
(usually `_id`). Emit an `identifier_alignment` edge `dbA.collA.f → dbB.collB.pk`
— **even when `f` and `pk` have different names**. Optionally confirm/boost with
value-overlap sampling of `f` vs `pk`.

## Confidence

- B (reference alignment) base ≈ 0.75; + value-overlap boost (scaled by ratio, cap 0.95).
- A (role-boost of a v1 edge): raise the v1 edge's confidence (e.g. +0.15, cap
  0.95) and relabel `kind="identifier_alignment"`.
- Deduplicate: if A and B produce the same endpoint pair, keep the
  higher-confidence one.

## Architecture (extends v1)

- `core/planning/cross_db.py`: add `align_by_identifier_role(semantics_by_loc,
  sample_values) -> list[CrossDbEdge]` (capability B) and a role-boost helper
  applied to `match_cross_db`'s output (capability A). A small data-agnostic
  `_matches_resource(target, collection)` (exact/singular/plural). `CrossDbEdge.kind`
  gains the string value `"identifier_alignment"` (no schema change — `kind` is a str).
- `core/planning/cross_db_resolver.py`: in addition to the field-name inventory,
  gather a `semantics_by_loc: dict[(database, collection), dict[field, (role,
  references)]]` from `describe_collection`'s `semantics` (governed; masked fields
  carry role `pii`, never an identifier role, so they cannot align). Run v1
  `match_cross_db` + signal-3 (A boost + B discovery), merge/dedupe, return.
- Tool: `guardmcp_relationships` already emits `cross_db_edges` — signal-3 edges
  flow through unchanged (no tool signature change).

## Governance

- Spans only `databases_allow`; roles read via the governed `describe_collection`;
  masked fields (role `pii`) never participate in alignment. Value sampling
  bounded + governed (reuses `sample_field_values`). No new surface.

## Back-compat

- If semantics/roles are absent or empty (e.g. field-semantics disabled or a
  collection with no inferable roles) → no signal-3 edges; v1 shared-name /
  value-overlap behavior is unchanged. Additive. `kind="identifier_alignment"` is
  a new value existing consumers treat as any other edge kind.

## Testing

- Matcher unit: (B) `foreign_identifier` `f references=R` in dbA + `primary_identifier`
  `_id` in dbB.R → `identifier_alignment` edge `dbA.collA.f → dbB.R._id` even when
  names differ; (A) a shared-name v1 edge with aligned endpoint roles → upgraded
  kind + higher confidence; dedupe A vs B; value-overlap boosts confidence; a
  masked/pii field never aligns; deterministic ordering.
- Resolver: gathers semantics from `describe_collection`; produces signal-3 edges
  scoped to allowed databases; masked field excluded.
- Integration via `guardmcp_relationships`: an `identifier_alignment` cross-DB
  edge appears for a reference-based link across two seeded databases.
- Data-agnostic: product-neutral names (`grp`/`xref`) with roles drive alignment.
- Back-compat: no roles → v1 edges only, unchanged; full regression + eval 42/42.

## Out of scope

Transitive multi-hop path composition (return identity→inventory→cost as one
path) — v2 still returns pairwise edges; the model composes the path.
