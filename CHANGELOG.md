# Changelog

All notable changes to GuardMCP are documented here. This project adheres to
[Keep a Changelog](https://keepachangelog.com/) conventions.

## [Unreleased]

## [0.0.1-alpha] — 2026-06-27

First public alpha. Policy-enforced multi-backend MCP server (MongoDB live;
PostgreSQL/MySQL plugins). Governance core (policy/risk/approval/masking/audit/
rate-limit), 44 MCP tools (`db_*` + `mongodb_*` aliases + 6 `guardmcp_*` meta),
query cost estimation, policy explain/simulator, type marshalling. Full notes:
[RELEASE_NOTES.md](RELEASE_NOTES.md). 546 tests, 38 evals.

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
Existing policies with explicit allow lists (incl. the bundled
`example.yaml` / `test_stdio.yaml`) are unaffected.

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

[Unreleased]: https://github.com/your-org/guardmcp/compare/v0.1.0...HEAD
