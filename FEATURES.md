# GuardMCP — Features

Policy-enforced, multi-backend MCP server for governed database access by AI agents.
**"AI proposes, GuardMCP decides."** A database-agnostic governance kernel fronting
MongoDB (live) + PostgreSQL + MySQL plugins, exposed through a discoverable MCP interface.

---

## Governance Core (database-agnostic — imports zero plugin code)

### Policy Engine
- Per-agent policies; **deny-by-default** (empty `collections.allow` = deny-all; `["*"]` = all; deny always wins)
- Collection allow/deny lists (overlap rejected at load)
- Action allow/deny lists
- `readonly` / `readwrite` mode — readonly blocks every write
- **Role inheritance** (`extends`, `role:*` templates, cross-file merge, cycle detection)
- **Temporal validity** (`not_before` / `not_after` — scheduled / temporary policies)
- **`apiVersion`** schema versioning (forward-compat)
- Connection allow-list (`connections_allow`) gates `switch_connection`
- Hot-reload from a **file or directory** of policies (mtime poll, atomic swap, keeps last-good on invalid YAML)

### Risk Engine
- LOW / MEDIUM / HIGH / CRITICAL classification per action
- **Scope escalation** — empty-filter `update_many` / `delete_*` escalates to CRITICAL (mass-mutation guard)
- **Cost-aware escalation (opt-in, additive)** — `escalate_for_cost(base, cost)` bumps risk when a query's estimated cost is HIGH/CRITICAL (collection scan / huge scan). NOT on the synchronous authorize hot path (estimation needs a DB round-trip); surfaced by `guardmcp_plan` and available to a future opt-in policy rule. `classify(action, params)` is unchanged (backward compatible).

### Query Cost Estimation (Feature 1)
- Each DB plugin estimates an op's cost via its **native explain** (MongoDB `explain(executionStats)`, Postgres `EXPLAIN (FORMAT JSON)`, MySQL `EXPLAIN FORMAT=JSON`) — SQL EXPLAINs are **plan-only, no execution**
- Core normalizes to ONE **frozen** `CostEstimate` (docs/keys examined, `collection_scan`, `index_used`, `estimated_cost` LOW/MEDIUM/HIGH/CRITICAL/UNKNOWN, duration, warnings) — the **raw explain plan is never exposed**
- **Shared `classify_cost` heuristic** keeps LOW/MEDIUM/HIGH thresholds identical across all backends (collection scan → HIGH; indexed + small → LOW)
- `DatabasePlugin.estimate()` has a **safe default** (returns UNKNOWN + warning) so existing/3rd-party plugins keep working; `Capability.ESTIMATE` is read-only/introspection (not a write cap)
- Exposed through `guardmcp_plan` as an **optional `cost` block** + `cost_aware_risk` — **best-effort**: any estimation failure yields UNKNOWN + a warning and **never fails the plan**

### Approval Workflow
- In-band `ctx.elicit()` confirmation + REST approval API
- **TOCTOU re-check** — policy re-evaluated at execute, not the cached decision from before the prompt
- Timeout → **deny** (never allow); graceful drain on shutdown; periodic prune of resolved approvals

### Field Masking
- Recursive key masking → `***masked***`
- **Per-collection** masks (`{collection: [...], "*": [...]}`) or flat global list
- **First-class dotted paths** (`contact.email` masks only that path; bare name = any depth)
- **Field allow-list** (data minimization — result projected to allowed fields, agent can't widen)
- **Depth-limit fail-safe** — redacts subtrees past depth 25 instead of leaking raw
- Aggregation masked-field-reference **denial** (blocks `$group`/`$project`/`$addFields` rename leaks)
- Single-pass fused transform, cached per policy + collection

### Audit
- Async **group-commit** (batched write + single fsync — no global serialization)
- **HMAC-SHA256 chain** — restart-persistent, atomic single-writer, optional `fail-closed` (abort op if unauditable)
- Masked values scrubbed from logged params
- `node_id` (multi-replica attribution) + **W3C trace_id** correlation across logs + records
- **Cross-platform location**: macOS `~/Library/Logs/guardmcp`, Linux `$XDG_STATE_HOME/guardmcp`, Windows `%LOCALAPPDATA%\guardmcp\logs`, Docker volume via `GUARDMCP_AUDIT_LOG_PATH`; fail-loud writability probe at startup

### Rate Limiting
- Token bucket per agent, idle-bucket eviction

### Type Marshalling (filter boundary)
- Schema-driven coercion of filter values to native types (date / ObjectId / Decimal128 / int)
- **Fail-loud `TYPE_MISMATCH`** instead of a silent empty result
- Extended-JSON escape hatch: `{$date}` / `{$oid}` / `{$decimal}` / `{$int}` / `{$long}`

---

## Plugin Architecture

- **`DatabasePlugin`** — the single public backend contract
- **`Capability`** model + `CapabilityRequest` (filter / sort / joins / returning / tx_id / predicate seam) + `CapabilityResult` (rows / affected / scalar)
- **`PluginRegistry`** — entry_points discovery, api-version gate, `manifest()` readable without instantiation or drivers
- **`CapabilityExecutorAdapter`** — bridges any plugin to the pipeline; neutral result view on every backend
- **Backends:** MongoDB (native, Motor) · PostgreSQL (asyncpg, optional) · MySQL (aiomysql, optional)
- Shared SQL **`Dialect`** core — Oracle / MSSQL = add a Dialect, not a copy
- **Seams (impl drops in without touching core):** transactions; distributed state (`ApprovalStoreProtocol` / `RateLimiterProtocol` / `AuditSinkProtocol`); `PrincipalResolver` identity; pluggable `ClientFactory` connection registry
- **Conformance kit** (`guardmcp.conformance`) for third-party plugin authors

---

## Security Controls

- `$where` / `$function` / `$accumulator` / `$out` / `$merge` blocked; aggregation pipeline **stage allow-list**
- `$lookup` / `$graphLookup` / `$unionWith` **cross-collection authorization**
- **Injection-safe SQL by construction** — identifier allow-list + values always parameterized
- Constant-time approval-token comparison; SSE/HTTP **refuses to start unauthenticated**
- YAML-injection-proof `guardmcp_setup`
- Sanitized errors (no DSN / stack leak); **frozen `ErrorCode` taxonomy** (code + retryable + suggested_action)

---

## MCP Interface

- Transports: **stdio · SSE · streamable-http**
- **44 tools** — 19 capability-neutral `db_*` + 19 `mongodb_*` aliases + 6 `guardmcp_*`:
  - Data: find, count, aggregate, explain, schema, indexes, insert_one/many, update_one/many, delete_one/many, create_index, drop_index
  - Discovery: list_collections, list_databases, stats, list_connections, switch_connection
  - Meta: **`guardmcp_status`** (connection + DB stats + version), **`guardmcp_setup`** (policy wizard), **`guardmcp_capabilities`** (per-collection permitted actions), **`guardmcp_plan`** (dry-run: decision / risk / approval / affected-estimate, no execution)
  - Policy introspection (read-only, single-source-of-truth — both reuse the SAME `GuardPipeline.evaluate` / `PolicyEngine.evaluate` authorization path, never a second evaluator):
    - **`guardmcp_explain_policy`** — explains why a `(agent, collection, action)` is allowed / denied / approval-required via an ordered rule trace the real engine populates as it runs (optional, gated `PolicyTrace`; zero hot-path cost when absent). Exposes only rule labels + results — never a raw policy dump or stack.
    - **`guardmcp_simulate_policy`** — what-if: evaluates the same request against the current and a proposed policy (via the additive `evaluate(..., policy_override=...)` seam), diffs the two `Policy` models into human-readable changes, and rates security impact (LOW/MEDIUM/HIGH). Never persists or executes the proposed policy.
- **ToolAnnotations** (readOnly / destructive / idempotent), uniform `{ok, data, error, meta}` envelope, JSON-schema examples, `UNSUPPORTED_CAPABILITY` per backend

---

## Multi-Connection & Config

- Typed connections via `GUARDMCP_CONNECTIONS` JSON: `{type, dsn, database, options}`
- Default + extra Mongo connections; runtime `switch_connection` (policy-gated, audited)
- Per-connection backend options (pool / ssl / schema / timeouts)

---

## Observability

- Structured JSON logging to stderr (`GUARDMCP_LOG_LEVEL` / `GUARDMCP_LOG_FORMAT`)
- `trace_id` + `span_id`, W3C `traceparent` parse/continue/emit

---

## Quality & Tooling

- **509 tests** (unit + integration + adversarial / red-team), 2 xfailed (mongomock limits)
- **Eval framework** — 38 declarative YAML cases across authorization / readonly / masking / approval / security / marshalling / pagination; console / JSON / JUnit reporters; `guardmcp eval` CLI
- **Live integration tests** — testcontainers (PostgreSQL / MySQL / MongoDB), skip-if-no-docker
- Plugin conformance suite
- Docs: README · SECURITY.md · CONTRIBUTING.md · PLUGIN_AUTHORS.md · ARCHITECTURE.md · CHANGELOG.md

---

## Deferred (apiVersion v2 / backlog)

- Capability-primary domain model (invert Action↔Capability primacy; retire legacy `Backend`)
- Predicate-AST as the primary filter contract (seam exists)
- Concrete distributed-state backends (Redis approvals / shared rate limiter / Kafka·QLDB audit sink — seams exist)
- Reliability/protocol harness scenarios (DB-down, slow-DB, malformed MCP frames, concurrent-write ordering)
