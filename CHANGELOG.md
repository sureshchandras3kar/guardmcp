# Changelog

All notable changes to GuardMCP are documented here. This project adheres to
[Keep a Changelog](https://keepachangelog.com/) conventions.

## [Unreleased]

## [0.0.1-alpha] — 2026-06-27

First public alpha. Policy-enforced, multi-backend MCP server that governs AI-agent
database access. MongoDB backend is well-tested (546 unit/integration tests,
38 policy/security evals); PostgreSQL and MySQL plugins are functional and live-tested
but newer. APIs may change before 1.0.

### Added

**Governance Core** (database-agnostic):
- Per-agent policy engine with collection/action allow-deny lists; **deny-by-default**
- Role inheritance (`extends`), temporal validity (`not_before`/`not_after`), `apiVersion` schema versioning
- Risk engine: LOW→CRITICAL classification with scope escalation (empty-filter mass-mutation → CRITICAL)
- Human approval workflow with in-band `ctx.elicit()` and REST API; TOCTOU re-check, timeout→deny
- Field masking: recursive, per-collection, dotted-path, field allow-list, depth-limit fail-safe
- Audit logging: async group-commit JSONL, optional HMAC-SHA256 chain, fail-closed mode, W3C trace correlation
- Rate limiting: token bucket per agent
- Type marshalling: fail-loud `TYPE_MISMATCH` on filter type errors (no silent empty results)

**Plugin Architecture**:
- Unified `DatabasePlugin` contract + `Capability` model for database-neutral operations
- MongoDB (native, Motor) · PostgreSQL (asyncpg, optional) · MySQL (aiomysql, optional)
- Query cost estimation: normalized `CostEstimate` per backend (explain never exposed)
- Entry-point discovery via `guardmcp.plugins` group; conformance kit for third-party authors

**MCP Interface** (44 tools):
- **19 capability-neutral `db_*` tools** (primary): find, count, aggregate, explain, schema, indexes, list_collections, list_databases, stats, insert_one/many, update_one/many, delete_one/many, create_index, drop_index, list_connections, switch_connection
- **19 `mongodb_*` aliases** for backward compatibility
- **6 `guardmcp_*` meta tools**: status (connection/DB stats/version), setup (policy wizard), capabilities (permitted actions), plan (dry-run with cost), explain_policy (decision trace), simulate_policy (what-if with impact rating)
- Uniform `{ok, data, error, meta}` envelope; MCP ToolAnnotations; frozen `ErrorCode` taxonomy

**Security Controls**:
- `$where`/`$function`/`$accumulator`/`$out`/`$merge` blocked; aggregation pipeline stage allow-list
- Cross-collection authorization for `$lookup`/`$graphLookup`/`$unionWith`
- Injection-safe SQL by construction (identifier allow-list + parameterized values)
- Constant-time approval-token comparison; SSE/HTTP refuse to start unauthenticated
- YAML-injection-proof setup; sanitized errors (no DSN/stack leak)

### Changed

#### Audit log default moved to a platform per-user state dir (minor behavior change)

The default audit log location moved from the cwd-relative `logs/audit.jsonl`
to a **platform-appropriate per-user state/log directory**, resolved to an
**absolute** path at startup:

- macOS: `~/Library/Logs/guardmcp/audit.jsonl`
- Linux: `$XDG_STATE_HOME/guardmcp/audit.jsonl` (else `~/.local/state/guardmcp/audit.jsonl`)
- Windows: `%LOCALAPPDATA%\guardmcp\logs\audit.jsonl`

Rationale: stdio MCP clients frequently launch with `cwd=/`, so the old
relative default tried to write `/logs/audit.jsonl` (root) or polluted the repo
checkout. The new default never depends on cwd. New `core/paths.py` helpers
(`default_state_dir`, `default_audit_log_path`, `resolve_audit_path`) implement
this with stdlib only. The resolved path is logged at startup (`audit_log_path`
event), and an unwritable audit dir now fails loud with an actionable error
instead of a raw traceback.

Explicit `GUARDMCP_AUDIT_LOG_PATH` is **unaffected**: an absolute path is used
as-is (e.g. a Docker volume), and a relative path is resolved under the state
dir — never against cwd.

### Security fixes

#### BREAKING — empty `collections.allow` is now DENY-ALL (AD-1, CRITICAL)

GuardMCP is now deny-by-default for collections. Previously an empty (or
omitted) `collections.allow` was treated as "no allow-list configured" and
silently permitted **every** collection — a wide-open footgun for a governance
tool. New semantics (`collection_permitted`, enforced in `PolicyEngine`):

- `deny` always wins (even over the wildcard);
- `allow: ["*"]` is the explicit "all collections" wildcard;
- a collection listed in `allow` is permitted;
- an **empty or non-matching** `allow` now **DENIES**.

Migration: to permit every collection, set `collections.allow: ["*"]`
explicitly. `guardmcp_setup` now writes `allow: ["*"]` when you answer `*`.
Existing policies with explicit allow lists (incl. the bundled `example.yaml`) are unaffected.

#### Masking depth-limit leak fixed (EC-3, HIGH)

`FieldMasker.mask` and `ResultTransformer._doc` previously returned the **raw**
sub-document once recursion passed `_MAX_DEPTH` (10), leaking masked fields
nested deeper than the bound. The bound is raised to 25 for normal nesting, and
beyond it the over-deep subtree is now redacted to a sentinel
(`{"***": "depth-limit-exceeded"}`) — fail-safe: when masking cannot be
guaranteed at that depth, the data is redacted rather than revealed. The no-rules
fast path is unchanged.

### Plugin architecture refactor (P1–P6, S-4)

Generalized GuardMCP from a MongoDB-only server into a database-agnostic core
with pluggable backends:

- **P1** — Introduced the backend-neutral plugin interfaces: `DatabasePlugin`
  ABC, `Capability` enum, `CapabilityRequest` / `CapabilityResult`, and the
  `GuardError` hierarchy (`GuardValidationError`, `GuardExecutionError`,
  `PluginError`, `PluginVersionError`).
- **P2** — Added `PluginRegistry` with entry-point discovery
  (`guardmcp.plugins` group) and `CORE_API_MAJOR` version compatibility checks.
- **P3** — Reworked MongoDB into a formal `MongoPlugin` that owns its
  backend-specific guard knowledge (banned stages/operators, `$lookup`
  cross-collection extraction) behind the generic contract.
- **P4** — Added a formal `PostgresPlugin`: pure, injection-safe SQL translation
  plus execution against an asyncpg pool (asyncpg optional dependency).
- **P5** — Added a `MySQLPlugin` mirroring Postgres with dialect deltas (`%s`
  placeholders, no `RETURNING`; affected-count + `lastrowid` in `meta`).
- **P6 / S-4** — Shipped the OSS plugin author kit: a reusable, importable
  conformance suite (`guardmcp.conformance`), conformance tests for all three
  builtins, and contributor docs (`docs/PLUGIN_AUTHORS.md`, `CONTRIBUTING.md`).

### Security hardening (CR-1..3, H1..3, S-1/2/3/5/8, P-1, R-1/2)

- **CR-1..3** — Code-review hardening of the request/translation path.
- **H1..3** — High-severity injection-surface fixes across the SQL backends.
- **S-1/2/3/5/8** — Validation tightening: raw-SQL escape hatches rejected,
  identifier allow-listing, operator allow-lists, and structural filter checks.
- **P-1** — Validate-before-execute ordering so unsafe requests never reach a
  live connection.
- **R-1/2** — Registry robustness: version-incompatibility and bad-plugin
  rejection.

### Known Limitations

- **PostgreSQL/MySQL plugins** are unit + live-tested but newer; connection lifecycle established lazily.
- **Distributed deployments**: approval store, rate limiter, and HMAC audit chain are per-process single-writer. Seams exist for distributed backends (Redis/Kafka) but no impls ship yet.
- **Agent identity** (`X-GuardMCP-Agent` header) is trusted only behind an authenticating gateway; pluggable `PrincipalResolver` seam exists but no JWT/mTLS impl ships.
- **Aggregation field masking** enforced by denial — pipelines referencing masked fields are blocked, preventing rename/alias bypasses but also some legitimate pipelines.
- **`$match` on masked fields** can leak existence/ordering via result counts; masking hides display values, not predicates.
- **Rate limiting** is in-memory per-process; does not coordinate across multiple instances.
- For complete details, see [SECURITY.md](SECURITY.md#known-limitations).

[Unreleased]: <repo-url>/compare/v0.0.1-alpha...HEAD
