# GuardMCP v0.0.1-alpha

**First public alpha.** A policy-enforced, multi-backend MCP server that governs
AI-agent database access. *AI proposes — GuardMCP decides.*

> **Alpha status:** the governance core and MongoDB backend are well-tested
> (546 tests, 38 policy/security evals). PostgreSQL/MySQL plugins are functional
> and unit + live-tested but newer. APIs may change before 1.0. Not yet
> recommended for production data without your own review.

---

## What it is

GuardMCP sits between any MCP client (Claude Desktop, Cursor, …) and your database.
Every read, write, and schema op is evaluated against a YAML policy — allow/deny,
readonly, masking, risk, approval, audit — before it reaches the backend. A
database-agnostic governance core fronts pluggable backends.

```
AI Client ──► GuardMCP core ──► plugin ──► MongoDB | PostgreSQL | MySQL
```

---

## Highlights

### Governance
- **Policy engine** — per-agent collection/action allow-deny, **deny-by-default**,
  `readonly`/`readwrite`, role inheritance (`extends`), temporal validity, `apiVersion`
- **Risk engine** — LOW→CRITICAL + scope escalation (empty-filter mass-mutation → CRITICAL)
- **Human approval** — in-band `ctx.elicit()` + REST API, TOCTOU re-check, timeout→deny
- **Field masking** — recursive, per-collection, dotted-path, field allow-list, depth-limit fail-safe
- **Audit** — async group-commit JSONL, optional HMAC chain, fail-closed, trace correlation,
  cross-platform location
- **Rate limiting** — token bucket per agent

### Backends & plugins
- **MongoDB** (native, Motor) · **PostgreSQL** (asyncpg) · **MySQL** (aiomysql) — SQL drivers optional
- One `DatabasePlugin` contract + `Capability` model; entry-point discovery; conformance kit
- **Query cost estimation** — normalized `CostEstimate` per backend (raw explain never exposed)
- **Type marshalling** — JSON filters coerced to native types; **fail-loud `TYPE_MISMATCH`**
  (no more silent empty results), extended-JSON escape hatch

### MCP interface
- Transports: **stdio · SSE · streamable-http**
- **44 tools** — capability-neutral `db_*` (primary) + `mongodb_*` (aliases) + 6 `guardmcp_*` meta:
  - `guardmcp_status` · `guardmcp_setup` · `guardmcp_capabilities` (what may I do?) ·
    `guardmcp_plan` (dry-run incl. cost, no execution) · `guardmcp_explain_policy` ·
    `guardmcp_simulate_policy`
- Uniform `{ok, data, error, meta}` envelope · ToolAnnotations · frozen `ErrorCode` taxonomy

### Security
- `$where`/`$function`/`$accumulator`/`$out`/`$merge` blocked; aggregation stage allow-list
- `$lookup`/`$graphLookup`/`$unionWith` **cross-collection authorization**
- **Injection-safe SQL by construction** (identifier allow-list + parameterized values)
- Constant-time approval token; **SSE/HTTP refuse to start unauthenticated**
- YAML-injection-proof setup; sanitized errors (no DSN/stack leak)

---

## Install

```bash
git clone <repo-url> guardmcp && cd guardmcp
pip install -e .                 # core (MongoDB)
pip install -e ".[postgres,mysql]"   # optional backends
```

5-minute setup: [QUICKSTART.md](QUICKSTART.md) · full install/config: [INSTALL.md](INSTALL.md).

---

## Known limitations (alpha)

- **PostgreSQL/MySQL** plugins are unit + live-tested but younger than the MongoDB path;
  their connection lifecycle is established lazily.
- **Distributed deployments:** approval store, rate limiter, and the HMAC audit chain are
  per-process (single-writer). Seams exist (`ApprovalStoreProtocol`/`RateLimiterProtocol`/
  `AuditSinkProtocol`) but no Redis/Kafka/QLDB impls ship yet — multi-replica audit is not
  yet centrally verifiable.
- **`X-GuardMCP-Agent` header** identity is trusted only behind an authenticating gateway;
  a pluggable `PrincipalResolver` seam exists but no JWT/mTLS impl ships.
- **Deferred to v2** (seams in place): capability-primary domain model, predicate-AST as the
  primary filter contract, transaction execution wiring.
- Count/sort over masked fields can leak existence/ordering (documented); masking hides
  display values, not their presence.

---

## Quality

- **546 tests** (unit + integration + adversarial/red-team), 2 xfailed (mongomock limits)
- **38 policy/security evals** (`python -m guardmcp.eval evals/cases/`)
- Live-backend integration tests (testcontainers PG/MySQL/Mongo, skip without Docker)
- Plugin conformance suite · ruff + mypy clean · CI-gated

---

## Notable security defaults

- **Deny-by-default:** empty `collections.allow` denies everything; use `["*"]` for all.
- **Fail-closed startup:** invalid policy, unwritable audit dir, or unauthenticated network
  transport → clear FATAL, not a silent or insecure start.

See [SECURITY.md](SECURITY.md) for the security model and reporting.

---

**Docs:** [README](README.md) · [QUICKSTART](QUICKSTART.md) · [INSTALL](INSTALL.md) ·
[FEATURES](FEATURES.md) · [ARCHITECTURE](docs/ARCHITECTURE.md) · [PLUGIN_AUTHORS](docs/PLUGIN_AUTHORS.md)

License: MIT.
