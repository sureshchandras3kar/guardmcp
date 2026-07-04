# Multi-Database Governance — Phase 2 (Backend Database Parameter) Design

Date: 2026-07-03
Status: Approved (design)
Branch: `feat/multi-db-phase2` (stacked on `feat/multi-db-governance` = Phase 1)
Parent design: `docs/superpowers/specs/2026-07-03-multi-database-governance-design.md`

## Goal

Thread the governed `database` from authorization (Phase 1) into EXECUTION and
result masking, so the resolved database is actually used to read, mask, and
guard — closing the three Phase-1→execution gaps. No MCP tool exposes the axis
yet (Phase 3). `database` defaults to the connection's configured DB, so
single-database behavior is byte-identical.

## Resolution (Phase 2 scope)

Effective database = explicit `database` argument → connection's configured
default. (The active-database *session* — `use_database` — is Phase 3.) The
pipeline threads the resolved value into evaluate, execution, and masking.

## Changes

1. **`MongoClient`** (`plugins/mongodb/client.py`): add
   `get_db(name: str | None = None)` → `self._client[name] if name else self._db`.
   `get_collection(name, database=None)` routes through `get_db(database)`.
   `_db` remains the default (constructed from the configured database).

2. **`MongoExecutor`** (`plugins/mongodb/executor.py`): `execute(collection,
   action, params, database=None)` and the introspection helpers
   (`collection_schema`, `collection_indexes`, `field_stats`,
   `list_collections`, `list_databases` unaffected, `explain_find_stats`,
   `explain_aggregate_stats`, `explain_find`, `explain_aggregate`) accept
   `database=None` and obtain their collection/db handle via `get_db(database)`.
   `database=None` → the configured DB (today's behavior). The schema/type/
   field-stats cache keys become `(database, collection)` so a collection name
   in two databases doesn't collide.

3. **`GuardPipeline`** (`core/pipeline.py`):
   - `run(agent, collection, action, params, incoming_traceparent=None,
     database=None)` threads `database` into its internal `evaluate(...)`
     (closes the execute-path gate bypass) and into `_execute_and_build`.
   - `_execute_and_build(req, policy, database=None)` calls
     `executor.execute(req.collection, req.action, params, database=database)`.
   - `execute_approved` likewise threads the request's `database`.
   - **Masking cache keying (Phase 2):** re-key `Policy.result_transformer` /
     `Policy.audit_masker` caches from `collection` to `(collection, database)`
     and add a `database` param that resolves mask + fields_allow via
     `scope_for(database)` (these were 1-arg at Phase-1 HEAD — this is Phase-2
     work, not pre-existing). `_build_success(raw, action, policy, collection,
     database=None)` uses `result_transformer(collection, database)`.
   - **Aggregation guard:** `_guard_aggregation(request, policy, database=None)`
     resolves foreign-collection permission via `policy.scope_for(database)`
     collections and masked-field refs via `mask_fields_for(collection,
     database)`.

4. **`_audit_params`** and audit calls thread `database` (Phase 1 already added
   the audit `database` field; ensure the masker used for audit param scrubbing
   is the database-aware one).

## Backward compatibility (hard requirement)

- `database=None` everywhere → the configured DB. Masking cache key
  `(collection, None)` is equivalent to today's `(collection)` key — existing
  single-DB masking, results, audit records, and the audit HMAC chain are
  unchanged.
- All new params are optional and trailing. No existing call site must change
  behavior; existing callers that pass no `database` get identical results.
- Executor cache: keying by `(database, collection)` with `database=None` for
  today's callers preserves current cache hits (the None bucket == the single
  configured DB).

## Security

- The execute path now honors the database gate: `run()` re-checks
  `evaluate(..., database)` so a disallowed database is denied before execution
  (previously `run()` called `evaluate()` without `database`).
- Result masking is applied with the target database's mask set — a field masked
  in DB-A is not leaked when the same collection name is read in DB-B.
- The aggregation guard enforces the target database's collection allow/deny and
  masked-field rules on `$lookup`/`$graphLookup`/`$unionWith`.
- No new connection/credential path; the URI still bounds reachable databases.

## Testing

- Executor: `execute`/introspection route to the named database (assert
  `get_db` receives it; cache keyed by `(database, collection)`).
- Pipeline `run()`: a disallowed database is denied on the execute path
  (`DATABASE_NOT_ALLOWED`) — proves the closed gap.
- Masking at execution: per-database mask set applied to results; cache does not
  cross-contaminate between databases for the same collection name.
- Aggregation guard: a `$lookup` to a collection permitted in DB-A but denied in
  the target DB is blocked.
- Back-compat regression: full existing unit + eval suites pass unchanged
  (single-DB path byte-identical); audit HMAC chain intact.

## Out of scope (Phase 3)

MCP tool optional `database` params; `use_database` active-session tool;
policy-filtered `list_databases`; `guardmcp_status` active/allowed-database
display.
