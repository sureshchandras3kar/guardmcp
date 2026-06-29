# GuardMCP

**Policy-enforced, multi-backend MCP server for governed database access. AI proposes. GuardMCP decides.**

GuardMCP sits between any MCP client (Claude Desktop, Cursor, OpenAI Agents) and your
database. Every read, write, and schema operation is evaluated against a YAML policy —
allow/deny, readonly, field masking, risk scoring, human approval, audit — before it
reaches the backend.

```
AI Client ──► GuardMCP core ──► plugin ──► MongoDB | PostgreSQL | MySQL
              (policy · risk · approval ·
               masking · audit · rate-limit)
```

A **database-agnostic governance core** fronts pluggable backends. MongoDB ships live;
PostgreSQL and MySQL are first-class plugins (optional drivers). Third parties can add a
backend without touching core — see [docs/PLUGIN_AUTHORS.md](docs/PLUGIN_AUTHORS.md).

---

## Why GuardMCP?

Without GuardMCP, any AI agent with database credentials can read, write, or drop anything.
GuardMCP sits between the agent and your database to **prevent exfiltration** (PII masking),
**block dangerous operations** (mass-delete/drop requires approval), and **enforce access control**
(deny-by-default, per-agent policies). Every decision is **audited** with tamper-evident logs.
Think of it as the security layer a database should have built in.

---

## Quick links

| | |
|--|--|
| **5-minute setup** (Claude Desktop) | [QUICKSTART.md](QUICKSTART.md) |
| **Install / Docker / backends / config reference** | [INSTALL.md](INSTALL.md) |
| **Architecture (public vs internal interfaces)** | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| **Write a backend plugin** | [docs/PLUGIN_AUTHORS.md](docs/PLUGIN_AUTHORS.md) |
| **Security policy** | [SECURITY.md](SECURITY.md) |

---

## Features (overview)

**Governance core (database-agnostic):**
- Per-agent policy: collection + action allow/deny, **deny-by-default**, `readonly`/`readwrite`
- **Role inheritance** (`extends`), **temporal validity** (`not_before`/`not_after`), `apiVersion`
- **Risk engine** LOW→CRITICAL + scope escalation (empty-filter mass-mutation → CRITICAL)
- **Human approval** (in-band `ctx.elicit()` + REST API), TOCTOU re-check, timeout→deny
- **Field masking** — recursive, per-collection, dotted-path, field allow-list, depth-limit fail-safe
- **Audit** — async group-commit JSONL, optional HMAC chain, fail-closed, trace correlation
- **Rate limiting** (token bucket per agent)
- **Type marshalling** — coerces JSON filters to native types; fail-loud `TYPE_MISMATCH` (never a silent empty result)

**Plugin architecture:**
- One `DatabasePlugin` contract + `Capability` model; entry-point discovery
- MongoDB (native) · PostgreSQL (asyncpg, optional) · MySQL (aiomysql, optional)
- **Query cost estimation** — normalized `CostEstimate` per backend (raw explain never exposed)

**Security:** `$where`/`$function`/`$out`/`$merge` blocked · pipeline stage allow-list ·
`$lookup`/`$graphLookup`/`$unionWith` cross-collection authorization · injection-safe SQL by
construction · constant-time approval token · SSE/HTTP refuse to start unauthenticated.

---

## Quickstart (stdio + Claude Desktop)

```bash
git clone <repo-url> guardmcp && cd guardmcp
pip install -e .
cp policies/example.yaml policies/policy.yaml   # edit: agent, allow, mask_fields
```

`~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "guardmcp": {
      "command": "/ABSOLUTE/PATH/TO/python",
      "args": ["-m", "guardmcp", "--transport", "stdio"],
      "env": {
        "GUARDMCP_AGENT": "claude",
        "GUARDMCP_MONGODB_URI": "mongodb://localhost:27017",
        "GUARDMCP_MONGODB_DATABASE": "mydb",
        "GUARDMCP_POLICY_PATH": "/ABSOLUTE/PATH/TO/guardmcp/policies/policy.yaml"
      }
    }
  }
}
```

**Must follow:** use the **absolute** Python path (Claude Desktop's PATH won't resolve a
shim); `GUARDMCP_AGENT` must equal the policy `agent:`; use an **absolute** policy path.
Full walkthrough + gotchas: [QUICKSTART.md](QUICKSTART.md).

**Docker / server mode** (SSE / streamable-http) — see [INSTALL.md](INSTALL.md#b-docker-server-mode--sse--streamable-http).
Networked transports **require** `GUARDMCP_APPROVAL_API_TOKEN` (the server refuses to
start without it).

---

## Policy file

```yaml
agent: claude            # must match GUARDMCP_AGENT
mode: readonly           # readonly | readwrite

collections:
  allow: [customers, orders]   # deny-by-default: omit/empty = DENY-ALL; ["*"] = all
  deny:  [payroll]             # deny always wins

actions:
  allow: [find, count, aggregate, collection_schema, collection_indexes, explain]
  # readwrite mode: also insert_one, update_one, delete_one, …

mask_fields:               # flat list (global) OR {collection: [...], "*": [...]}
  - password
  - email                  # dotted paths supported: contact.email

approval:                  # readwrite gates
  high: true               # update_*, delete_one, drop_index
  critical: true           # delete_many, drop
```

Also supported: `extends` (role inheritance), `not_before`/`not_after` (temporal),
`fields_allow` (result projection allow-list), `connections_allow` (gate `switch_connection`).
Multiple policies in one file under `agents:`, or a **directory** of policy files
(hot-reloaded). See `policies/example.yaml` for details.

---

## MCP tools (44)

Capability-neutral **`db_*`** names are primary; **`mongodb_*`** aliases are kept for
backward compatibility. Uniform `{ok, data, error, meta}` envelope; destructive tools
carry MCP annotations.

*Note:* Throughout these tools, **resource** is the backend-neutral term for a MongoDB
collection or SQL table. Tool parameters use `collection` for MongoDB compatibility.

| Group | Tools |
|-------|-------|
| Read | `db_find` · `db_count` · `db_aggregate` · `db_explain` |
| Discovery | `db_schema` · `db_indexes` · `db_list_collections` · `db_list_databases` · `db_stats` · `db_list_connections` · `db_switch_connection` |
| Write (readonly-blocked, approval-gated) | `db_insert_one/many` · `db_update_one/many` · `db_delete_one/many` · `db_create_index` · `db_drop_index` |
| Governance / meta | `guardmcp_status` · `guardmcp_setup` · `guardmcp_capabilities` · `guardmcp_plan` (dry-run incl. normalized cost) · `guardmcp_explain_policy` · `guardmcp_simulate_policy` |

`guardmcp_capabilities` (what may I do?) and `guardmcp_plan` (what would this do, without
executing?) let an agent plan deterministically instead of trial-and-error.

---

## Configuration

All settings are `GUARDMCP_`-prefixed env vars. Highlights:

| Variable | Default | Notes |
|----------|---------|-------|
| `GUARDMCP_AGENT` | `default-agent` | must match policy `agent:` |
| `GUARDMCP_MONGODB_URI` / `_DATABASE` | `mongodb://localhost:27017` / `guardmcp` | default connection |
| `GUARDMCP_POLICY_PATH` | `policies/policy.yaml` | file **or directory**; absolute for stdio |
| `GUARDMCP_TRANSPORT` | `stdio` | `stdio` · `sse` · `streamable-http` |
| `GUARDMCP_CONNECTIONS` | `{}` | JSON typed PG/MySQL connections |
| `GUARDMCP_APPROVAL_API_TOKEN` | `""` | **required** for networked transports |
| `GUARDMCP_AUDIT_HMAC_SECRET` | `""` | tamper-evident audit chain |
| `GUARDMCP_AUDIT_FAIL_CLOSED` | `false` | abort op if unauditable |
| `GUARDMCP_AUDIT_LOG_PATH` | platform state dir | macOS `~/Library/Logs/guardmcp/`, Linux `$XDG_STATE_HOME`, Windows `%LOCALAPPDATA%` |

Complete reference: [INSTALL.md#configuration](INSTALL.md#configuration).

---

## Audit log

Every decision writes a JSONL record (params scrubbed of masked values):

```json
{"timestamp":"2026-06-27T10:00:00Z","agent":"claude","collection":"customers",
 "action":"find","status":"allowed","reason":"request permitted by policy.",
 "risk":"LOW","request_id":"…","trace_id":"…","node_id":"","params":{"filter":{}}}
```

Async group-commit; optional HMAC chain (`GUARDMCP_AUDIT_HMAC_SECRET`); writes go to a
platform state dir by default (see [INSTALL.md](INSTALL.md)). Structured app logs go to
stderr (JSON), not the audit file.

---

## CLI / operations

The same `guardmcp` entry point doubles as an operator/CI CLI. Run `guardmcp --help`
for the full list; bare `guardmcp` (or `python -m guardmcp`) and any `--transport …`
flag still start the server (back-compat).

| Command | What it does |
| --- | --- |
| `guardmcp version` | Print version + policy/core API + plugin manifest versions. |
| `guardmcp doctor` | Readiness report (config, policy, audit path, DB). DB unreachable → WARN, not failure. |
| `guardmcp config validate` | Validate settings/H1/paths only (no DB call). |
| `guardmcp policy lint <path> [--strict]` | Load + danger-check policies; `--strict` makes warnings fail. |
| `guardmcp audit verify <log> --secret <s>` | Verify the audit HMAC chain; reports the first broken line. |
| `guardmcp capability inspect <type>` | Print one backend's manifest (no connection). |

**CI usage:** `policy lint` and `audit verify` exit nonzero on failure, so they drop
straight into a pipeline (e.g. fail the build on a dangerous policy under `--strict`, or
on a tampered audit log).

> `guardmcp version` reads installed package metadata — if it shows a stale version,
> re-run `pip install -e .`.

---

## Multi-backend (PostgreSQL / MySQL)

```bash
pip install -e ".[postgres,mysql]"
export GUARDMCP_CONNECTIONS='{"analytics":{"type":"postgres","dsn":"postgresql://…","database":"app"}}'
```

The same governance (policy/risk/approval/audit/masking) applies to every backend. A
backend rejects unsupported capabilities (e.g. `aggregate` on SQL) with
`UNSUPPORTED_CAPABILITY`. See [INSTALL.md#backends](INSTALL.md#backends).

---

## Troubleshooting

**Python path resolution fails:** Use the **absolute** path to the Python interpreter in Claude Desktop config (e.g. `/usr/local/bin/python3`), not a shim or `python3` from PATH.

**`GUARDMCP_AGENT` mismatch:** The env var must exactly match the policy `agent:` field.

**Networked transports (SSE/HTTP) fail to start:** Set `GUARDMCP_APPROVAL_API_TOKEN` to a non-empty token before starting the server.

**Audit log won't write:** Check that the audit directory is writable. Default is a platform state dir (`~/Library/Logs/guardmcp` on macOS); set `GUARDMCP_AUDIT_LOG_PATH` to an absolute path if needed.

**Policy denies everything:** Empty `collections.allow` means deny-all. Set `allow: ["*"]` to permit all collections, or list specific collections explicitly.

For detailed troubleshooting: see [QUICKSTART.md](QUICKSTART.md) and [INSTALL.md](INSTALL.md).

---

## Development

```bash
pip install -e ".[dev]"
pre-commit install
python -m pytest -q                   # 591 passed (no real DB — mongomock)
python -m guardmcp.eval evals/cases/  # 38/38 policy/security evals
ruff check src/ tests/ && python -m mypy src/guardmcp
```

Live-backend tests (real PG/MySQL/Mongo via Docker, skip without it):
`pip install -e ".[test-live]" && python -m pytest -m integration`.
Contributing + plugin authoring: [CONTRIBUTING.md](CONTRIBUTING.md) · [docs/PLUGIN_AUTHORS.md](docs/PLUGIN_AUTHORS.md).

---

## License

MIT — see [LICENSE](LICENSE).
