# Multi-Database Governance — Design

Date: 2026-07-03
Status: Approved (design); phased. Phase 1 is the buildable unit.
Branch: `feat/multi-db-governance`

## Problem

GuardMCP pins one database per connection (`MongoClient._db = client[database]`).
A single MongoDB URI can reach many databases (as any GUI client does), yet
GuardMCP forces a reconfigure/relaunch per database. That is worse UX than every
mainstream database MCP.

## What other database MCP servers do (reference)

- **Official MongoDB MCP** (`mongodb-js/mongodb-mcp-server`): connection string =
  the *cluster*; `database` + `collection` are **per-call parameters** on
  `find`/`aggregate`/`count`/`insert`/… — not pinned. Runtime `connect` /
  `switch-connection`. Scoping via `--readOnly`, `disabledTools`, connection-string
  reach.
- **Multi-DB servers** (bytebase/dbhub, FreePeak db-mcp, Legion): **named
  connections** (connection IDs), lazy-loaded, pooled; read-only mode, row limits,
  timeouts; dedicated read-only DB user recommended.

**Industry norm:** connection = server; database is a request dimension
(per-call and/or switchable); many named connections. GuardMCP's differentiator
is **governance** — so the design is *database as a **governed** request
dimension*.

## Design: database as a governed dimension

### Access model (both modes — matches official MCP + shell UX)
- **Active database (session):** a default database; `use_database(name)`
  switches it (audited, policy-gated). Shell-like `use`.
- **Per-call `database` override:** data/introspection tools accept an optional
  `database` parameter (official-MCP style). Explicit, stateless.
- **Resolution order:** explicit param → active database → connection default.
- Connection stays = URI/cluster; named connections retained. One URI now serves
  many databases without relaunch.

### Governance keyed by (connection, database) — the non-negotiable edge
A database is never accessed ungoverned. Policy gains **database scoping**,
additive to the existing flat model:

```yaml
agent: claude
mode: readonly
# NEW — deny-by-default gate: which databases this agent may touch.
databases_allow: ["corestack_identity", "heatstack"]
# NEW — per-database scope blocks. Each mirrors the existing flat policy shape.
databases:
  corestack_identity:
    collections: { allow: ["user", "project"], deny: [] }
    mask_fields: ["password", "email"]
    fields_allow: []
  heatstack:
    collections: { allow: ["*"] }
    mask_fields: ["secret", "token"]
# NEW — applied to any allowed database WITHOUT a specific block.
default:
  collections: { allow: [] }         # deny-all by default (secure)
  mask_fields: ["password", "secret", "token", "api_key"]
# Existing flat fields remain valid (back-compat, see below).
```

Rules:
- A database not in `databases_allow` → **hard deny + audit** (no silent
  cross-DB roam). Empty `databases_allow` + no `databases` block = single-DB mode
  (back-compat, see below).
- Effective policy for `(database, collection)` resolves: per-database block →
  `default` block → flat top-level fields. Masking/`fields_allow`/collection
  allow/deny all resolve at `(database, collection)`.
- Audit records `connection + database + collection`. Schema/type/relationship
  caches are keyed by `(connection, database, collection)`.

### Backend / plugin refactor (stays database-agnostic)
- `MongoClient._db` pin → `get_db(name: str | None)` returning `client[name]`
  (default retained). `get_collection(name, database=None)`.
- Executor + `DatabasePlugin` methods gain an optional `database` argument
  threaded to the client. SQL plugins (db ≈ DSN) treat a non-matching `database`
  as unsupported → deny (safe default keeps the contract generic).
- `list_databases` is filtered to policy-allowed databases (discovery parity with
  the existing collection discovery).

### Backward compatibility (hard requirement)
- No `databases`/`databases_allow`/`default` in a policy → behaves exactly as
  today: the flat `collections`/`mask_fields`/`fields_allow` apply to the single
  configured/default database. All new params optional; all new tool params
  optional. `mask_fields` already supports the flat-list OR dict form — the
  per-database block reuses that shape.
- Reuses existing forward-compat seams: `api_version`, `extends` role
  inheritance, `connections_allow`.

## Phasing (each phase = its own spec→plan→build)

**Phase 1 — Governance core (this spec's buildable unit).** Policy model gains
`databases_allow`, `databases: dict[str, DatabaseScope]`, `default: DatabaseScope`.
Add `Policy.scope_for(database)` returning the effective collection/mask/field
rules, and make `mask_fields_for` / collection permission / `fields_allow`
database-aware. `PolicyEngine.evaluate` + `GuardPipeline.evaluate` take a
`database` and enforce `databases_allow` (deny + audit on miss). Audit records
carry `database`. **No backend change yet** — database defaults to the active/
configured one, so behavior is identical for single-DB users; the new axis is
*enforced* and *tested* even before tools expose it.

**Phase 2 — Backend database parameter.** `MongoClient.get_db(name)`, executor +
plugin `database` argument, caches keyed by `(connection, database)`. Wire the
resolved database from Phase 1 into execution.

**Phase 3 — Tools/UX.** Optional `database` param on data/introspection tools;
`use_database(name)` (governed, audited); `list_databases` filtered to allowed
databases; `guardmcp_status` shows active database + allowed databases.

## Security review

- Deny-by-default on the database axis: unknown/unlisted database → denied +
  audited, never silently served.
- Masking and field-allow resolved per `(database, collection)` — a lax rule in
  one DB never widens another.
- Every database access audited with the database name (attributable).
- No new credential path; the URI still bounds what is physically reachable.
- The planning/context features (already shipped/in-flight) inherit this: they
  read metadata only through the governed accessors, now database-scoped.

## Testing strategy

- Policy: `scope_for` resolution (per-db > default > flat); `databases_allow`
  deny; back-compat (flat policy unchanged when no `databases` block); masking/
  field-allow per database.
- Engine/pipeline: evaluate denies a disallowed database (+ audit record has the
  database); allowed database resolves the right collection rules.
- Adversarial: request a collection allowed in DB-A but issued against DB-B where
  it is denied → denied. Masked field in DB-A not masked in DB-B → each honored
  independently.
- Back-compat regression: existing single-DB policies + tests pass unchanged.

## Out of scope (future)

Cross-database joins/`$lookup` across databases; per-database rate limits;
per-database connections in `GUARDMCP_CONNECTIONS` (still supported as named
connections, orthogonal to the in-connection database axis).
