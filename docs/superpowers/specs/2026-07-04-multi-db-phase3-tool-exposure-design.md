# Multi-Database Governance — Phase 3 (MCP Tool Exposure) Design

Date: 2026-07-04
Status: Approved (design)
Branch: `feat/multi-db-phase3` (off the context-engine branch, after Phase 1+2 merged as 642639a)
Parent design: `docs/superpowers/specs/2026-07-03-multi-database-governance-design.md`

## Goal

Expose the governed `database` axis (built in Phases 1–2) to MCP clients so an AI
agent can read/write across multiple databases on one connection — enabling
multi-database workflows via orchestrated per-hop calls. Backward compatible:
omitting `database` (and setting no `databases_allow`) behaves exactly as today.

## Use-case framing (important)

MongoDB CANNOT join across databases in a single engine query. A workflow that
spans identity + inventory + cost_management is done as **AI-orchestrated
multi-hop**: Claude issues one governed call per database and stitches results in
reasoning, e.g.:

1. `find(database="corestack_identity", collection="user", …)` → account ids
2. `find(database="resource_inventory", …, filter={account_id:{$in:[…]}})` → inventory
3. `aggregate(database="billing_and_cost_analytics", …)` → cost

Phase 3 provides the per-call `database` selector that makes each hop possible and
governed. Making the join keys *known* to the model (so it doesn't guess) is
**cross-database relationship discovery** — a follow-up Context-Engine slice, out
of scope here.

## Changes

### 1. Per-call `database` parameter
Add an optional `database: str | None = None` parameter to the data +
introspection + write tools:
- Read/introspection: `find`, `count`, `aggregate`, `collection_schema`,
  `collection_indexes`, `explain` (both `db_*` and `mongodb_*` aliases).
- Write: `insert_one`/`insert_many`, `update_one`/`update_many`,
  `delete_one`/`delete_many` (and DDL if exposed).
Each threads `database` into `pipeline.run(..., database=)` (or the
`_run_with_confirm` path for writes) → the Phase-2 execution/masking/gate.
Resolution when a tool omits `database`: **active session db → connection
default** (see 2).

### 2. `use_database(name)` — active-database session
A governed tool that sets a **server-level active database** used by subsequent
tool calls that omit a per-call `database`.
- State: a mutable active-database holder on `ToolContext`/`AppContext` (single
  active db for the server; single-agent stdio model). Read by tools to resolve
  the effective database.
- Governed + audited exactly like `switch_connection`: denied (with
  `DATABASE_NOT_ALLOWED`) if `databases_allow` is non-empty and `name` is not in
  it; the switch is audited.
- **Reset on `switch_connection`**: switching connections clears the active db
  back to the new connection's configured default (avoids a stale active db from
  another connection).
- Resolution order (final): per-call `database` → active session db → connection
  configured default.

### 3. `list_databases` — policy-filtered
Filter the returned databases to those the agent may access: when
`databases_allow` is non-empty, return only those (intersected with what the
server can see); empty `databases_allow` → return all reachable (back-compat).
Discovery parity with `discover_collections`.

### 4. `guardmcp_status` — show active + allowed databases
Add `active_database` and `allowed_databases` (from `databases_allow`) to the
status payload.

## Governance & back-compat

- Both the per-call `database` and the `use_database` switch are enforced by the
  Phase-1 gate (`Policy.database_permitted` → `DATABASE_NOT_ALLOWED`).
- `use_database` and per-call denials are audited (database recorded — Phase 1).
- No `databases_allow` set + no `database` passed → the effective database is the
  connection default and every tool behaves byte-identically to today. All new
  params optional; `use_database`/status additions are additive.
- Writes: the per-call `database` flows through the existing confirm/approval path
  (`_run_with_confirm` → `run`/`execute_approved`), which already threads
  `database` (Phase 2), so approval + execution both target the chosen db.

## Security

- An agent can only reach databases permitted by `databases_allow`; per-call and
  session paths both gate. `list_databases` never reveals a denied database name.
- Masking/collection rules resolve per the effective database (Phase 2), so a
  multi-hop workflow is governed independently at each hop.
- No new connection/credential surface; the URI still bounds reachable databases.

## Testing

- Per-call `database` reaches `pipeline.run(..., database=)` for read + write
  tools (assert threading); a denied database → `DATABASE_NOT_ALLOWED` and no
  execution.
- `use_database`: denies an unlisted db (audited); sets the active db; a
  subsequent tool call with no `database` uses it; a per-call `database`
  overrides the session; `switch_connection` resets it.
- `list_databases` filtered to `databases_allow`; empty allow → all.
- `guardmcp_status` shows `active_database` + `allowed_databases`.
- Full back-compat: single-DB (no database, no databases_allow) unchanged;
  existing tool tests + eval (42/42) pass.

## Out of scope (follow-up Context-Engine slice)

Cross-database relationship discovery (telling the model the join keys across
identity/inventory/cost) — the "smart join" that makes multi-DB reasoning
reliable. Also: per-connection active-db (Phase 3 uses a single server-level
active db).
