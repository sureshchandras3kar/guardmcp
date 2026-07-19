# GuardMCP — Feature Status

> Snapshot of feature completion. Derived from the codebase (v0.0.1a1) and
> `docs/PROJECT_SSOT.md`. Statuses: ✅ Completed · 🚧 In Progress / ⚠ Partial ·
> ❌ Not Started (incl. 🧩 Planned). Update in the same PR as behavior changes.

## ✅ Completed

| Feature | Notes |
|---|---|
| Live-MongoDB verification suite | `tests/integration/live_mongo/` (53 tests, testcontainers `mongo:7`, real motor driver — zero mongomock) covering: (A) golden path/core governance — deny-by-default, readonly, recursive masking, aggregation guard, approval confirm/decline, audit chain, real-BSON type marshalling; (B) all 27 `db_*` tools incl. read/discovery/write against a real server; (C) all 9 `guardmcp_*` meta tools; (D) this session's newest features (cost escalation vs real EXPLAIN, per-connection active-db, cross-DB/data-trust vs real data, byte-budget truncation, `/metrics`); (E) multi-database/multi-connection (`databases_allow`, per-DB masking, per-DB aggregation guard, `switch_connection`+`use_database` at the tool layer). Found and fixed 3 real bugs mongomock had hidden (see below) |
| Bug fix: `ToolError` bypassed the structured error envelope | `_validation_guard` only caught `GuardValidationError`/`ValueError`/`GuardError` — the mongodb/guard.py validators (banned aggregation operator, malformed pipeline/db-level-stage shape) raise FastMCP's native `ToolError`, which propagated uncaught instead of the codebase's own `{ok:false,error:{code:"VALIDATION"}}` envelope every other validation failure gets. Fixed: `_validation_guard` now also catches `ToolError` |
| Bug fix: `MongoClient.list_databases()` crashed against the real driver | `for db in result` on the awaited `list_databases()` result — real Motor returns a `CommandCursor` (needs `.to_list()`/`async for`), not a plain list; mongomock's fake silently returned a plain list, hiding this for every prior unit test. Fixed with `await cursor.to_list(length=None)` |
| Bug fix: `db_aggregate_db`'s `$currentOp`/`$listLocalSessions` didn't target `admin` | Real MongoDB rejects these elsewhere ("$currentOp must be run against the 'admin' database") — the executor was aggregating against the request's target database instead. Fixed: these two stages now always route to `admin` regardless of the request's `database` param; `$documents`/`$queryStats`/`$changeStream` are unaffected (still request-scoped) |
| Bug fix: `guardmcp_setup` wizard's "readwrite" mode granted zero write actions | `actions.allow` was hardcoded to a read-only list regardless of the `mode` answer — a new user picking "readwrite" got a policy that silently behaved like readonly until hand-editing the generated YAML. Fixed: `mode="readwrite"` now appends every `WRITE_ACTIONS` value |
| Bug fix: `guardmcp_status` showed the wrong database after switching connections | `db_name` was hardcoded to `settings.mongodb_database` (the default connection's single global config value) regardless of which connection was actually active. Fixed: resolves session `active_database` override → active connection's own `database` → settings fallback |
| Policy engine (per-agent, deny-by-default) | collections/actions/mode/mask/fields_allow/approval/connections_allow/temporal/extends/api_version |
| Per-database policy scoping | `databases_allow`, `databases{}`, `default`; `DATABASE_NOT_ALLOWED` gate |
| Field masking + field-allow projection | recursive key-name masking, per-`(collection,database)` cache |
| Aggregation guard | blocks cross-collection / masked-field leaks in pipelines; resolves against the PER-DATABASE scope (`policy.scope_for(request.database)`), not a flat policy — a prior stale doc claimed otherwise, verified against code + `test_multidb_execution_masking.py` |
| Risk engine | Action → RiskLevel |
| Approval workflow | in-band elicit + token-gated REST API; TOCTOU re-check; REST endpoints (list/get/decide) + token auth (missing/wrong/correct, all 3 endpoints) covered in `test_approval_api_endpoints.py` |
| Audit log | append-only JSONL, HMAC chain, node_id, fail-closed option |
| Rate limiting | per-agent token bucket |
| Type marshalling | filter→BSON coercion, loud `TYPE_MISMATCH` |
| MongoDB backend | full CRUD/aggregate/DDL/introspection + explain-based cost |
| MCP tool surface | `db_*`/`mongodb_*` (27) + `guardmcp_*` meta (9), dual-named |
| mongodb-mcp-server parity gaps closed | `db_create_collection`/`db_drop_collection`/`db_rename_collection` (Action.DROP already fully wired — was just missing tool registration); `db_collection_storage_size` (collStats); `db_aggregate_db` (DB-level `$currentOp`/`$changeStream`/`$documents`/`$listLocalSessions`/`$queryStats` — verified against mongodb-mcp-server's `aggregateDB.ts`, NOT collection data; `$changeStream` bounded to a short best-effort window, no persistent-watch primitive exists); `db_logs` (admin `getLog`); `db_export` (already-masked find/aggregate → local file, reuses the exact `pipeline.run()` masking path, never a separate code path); new `Capability.LOGS`. Deliberately NOT built: ad-hoc `connect` (arbitrary URI) and `drop-database` — both would let an agent bypass the pre-registered-connection / no-whole-DB-destruction policy boundary |
| `/metrics` Prometheus endpoint | `core/metrics.py` (in-process counter registry, no new dependency); `GuardPipeline._audit_event` increments `guardmcp_requests_total{action,status}` on every governed operation; exposed at `/metrics` on the approval API, no auth (same posture as `/healthz`) |
| Multi-database governance (Phases 1–3) | per-DB authorization, execution threading, tool exposure (`use_database`, per-call `database`) |
| Connection switching | named connections, `switch_connection`, `connections_allow` |
| `guardmcp_plan` (concrete-op dry-run) | decision/risk/approval/would_affect/cost |
| Query planning (`guardmcp_plan_query`) | ambiguity + relationships + ranked plans (advisory, no-LLM) |
| Relationship discovery (within-DB) | FK/naming/index graph |
| Cross-DB relationships v1 | shared-name + value-overlap join keys |
| Cross-DB transitive path composition | `compose_transitive_paths()`; `guardmcp_relationships.cross_db_paths`; chains pairwise edges (identity→inventory→cost), no node revisit, weakest-link confidence |
| Cost→risk live escalation (opt-in) | `Policy.max_cost`; `GuardPipeline._maybe_escalate_for_cost` in `run()`; zero I/O unless an agent sets `max_cost`; escalated risk only flips ALLOWED→APPROVAL_REQUIRED via existing `approval.high`/`approval.critical` flags |
| Per-connection active database | `ConnectionEntry.active_database`; `ConnectionRegistry.get_active_database()`/`set_active_database()`; `db_use_database` now stored on the currently-active connection, so switching away and back restores that connection's own remembered database instead of a single shared server-level slot |
| Unified `guardmcp_context` bundle tool | Same payload as `guardmcp_plan_query` (ambiguity/relationships/plans) PLUS `cross_db_edges`/`cross_db_paths` PLUS `semantics`, capped to the top-N (default 3) most-connected collections by `rank_by_centrality()` — bounded cost, not one `describe_collection` per accessible collection |
| Compact/verbose response mode (token minimization) | Opt-in `verbosity="compact"` on `guardmcp_relationships`/`guardmcp_plan_query`/`guardmcp_context` — `_strip_evidence()` recursively drops only the human-readable `evidence` reasoning-trace field; `kind`/`confidence`/`role`/`overlap_ratio`/etc. (all decision-relevant data) untouched. Default stays `"full"` (unchanged output); audit log always records full detail regardless of `verbosity` |
| Semantics repeat-call stamps (token minimization) | `guardmcp_context`'s `known_stamps` param + `semantics_stamps` response key — agent echoes back a stamp from an earlier call; unchanged collections return `{"unchanged_since": stamp}` instead of full field data. No server-side session state (`_semantics_stamp()` is a pure content hash); stale/wrong/absent stamp always falls back to full data. Default (`known_stamps` omitted) is byte-identical to before this feature |
| Byte-budget response capping (token minimization) | `core/response_limits.py` (`cap_by_bytes`/`cap_lines`, data-agnostic, no backend import) layered ON TOP of the existing doc-COUNT caps in `db_find`/`db_aggregate`/`db_aggregate_db`/`db_logs` — a small number of large documents (or one huge log line) is now capped by size too, not just count. Every capped response carries an explicit `truncated_by_size` flag (or, for `db_aggregate`, the existing `_guardmcp_truncated` marker doc) — never a silent truncation |
| Tool↔pipeline signature-contract test, extended | `_CALL_SITE_KWARGS` now covers all 9 distinct `GuardPipeline` methods called from the tool layer (was 5) — added `_get_executor`/`active_connection`/`list_connections`/`switch_connection_audited`; 2 new integration smokes (`db_create_collection`, `db_export`) drive this session's newest tools through the REAL pipeline, not a lenient fake |
| Rate limiting integration/concurrency coverage | `tests/integration/test_rate_limit_integration.py` — real `GuardPipeline.run()` + real `RateLimiter` end to end (RATE_LIMITED short-circuits before `evaluate()` even runs); concurrent `asyncio.gather` token-bucket race test (never over-allows past `burst`); multi-agent concurrent isolation; idle-bucket eviction past the 1024 threshold |
| Performance / load test suite | `tests/integration/test_performance.py` (new `perf` pytest marker) — sequential + concurrent `pipeline.run()` throughput (generous bounds, not strict SLAs), concurrent multi-agent load, and a policy-evaluation microbenchmark. Concurrency correctness check: the audit HMAC chain (order-sensitive, single-writer/group-commit) still verifies (`verify_chain`) with the exact expected record count after 100+ concurrent requests |
| Cross-DB relationships v2 (signal 3) | identifier-role alignment (foreign→primary across DBs) |
| Field semantics | per-field roles (primary/foreign/tenant/timestamp/enum/pii) in `db_schema` |
| Data-trust signals v1 (nullability/distribution/freshness) | `FieldSemantics.null_ratio`/`distinct_ratio`/`oldest_value`/`newest_value`, surfaced from `FieldStat` in `db_schema`/`guardmcp_context` semantics blocks; freshness needed a `build_field_stats()` extension to track datetime min/max (previously dropped); masked fields still get zero signals |
| Policy explain / simulate | `guardmcp_explain_policy`, `guardmcp_simulate_policy` |
| Capabilities / status / setup | `guardmcp_capabilities`/`status`/`setup` |
| stdio transport | private single-agent server |
| Eval harness | YAML cases → console/json/junit; 42 cases / 8 areas |
| DatabasePlugin contract | backend-neutral capability interface + CapabilityExecutorAdapter |

## 🚧 In Progress / ⚠ Partially Complete

| Feature | Status | Gap |
|---|---|---|
| PostgreSQL backend | ⚠ Partial | plugin + SQL translate present; **not tested against a live Postgres** [Needs Verification] |
| MySQL backend | ⚠ Partial | plugin + SQL translate present; **not tested against a live MySQL** [Needs Verification] |
| SSE / streamable-http transport | ⚠ Partial | works for MCP; DB tools hit a Motor "MongoClient after close" bug [Needs Verification: fixed?]; 1 flaky test |
| Multi-replica audit / durable approvals | ⚠ | HMAC chain single-writer; approvals in-memory (non-durable) |

## ❌ Not Started (incl. 🧩 Planned)

| Feature | Kind | Note |
|---|---|---|
| Entity-map / business-entity clustering | 🧩 Planned | Context Engine slice; needs a dedicated design pass (no existing infra — algorithm/entity-boundary/confidence model all undefined) |
| AI-safety layer (prompt-injection / exfiltration / anomaly detection) | 🚫 Out of scope | conflicts with GuardMCP's deterministic/no-LLM architecture (CLAUDE.md hard rule #1); a separate product decision, not a GuardMCP backlog item |
| Additional backends (Oracle/SQL Server/SQLite/Snowflake/BigQuery) | 🧩 Planned | via DatabasePlugin contract |
| Distributed audit sink (Redis/Kafka/QLDB) | 🧩 Planned | Protocol seam exists |
| Frontend / UI | ❌ N/A | GuardMCP is a server; UI = the MCP client |
| Login / session / JWT / OAuth | ❌ N/A by design | identity is operator-set / trusted-gateway header |
