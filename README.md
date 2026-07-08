# GuardMCP

**Policy-enforced, multi-backend MCP server for governed database access.**
_AI proposes. GuardMCP decides._

![status: alpha](https://img.shields.io/badge/status-alpha-orange)
![python: 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)
![MCP](https://img.shields.io/badge/MCP-stdio%20%7C%20SSE%20%7C%20HTTP-green)
![license: MIT](https://img.shields.io/badge/license-MIT-black)

GuardMCP sits between an MCP client (Claude Desktop, Cursor, …) and your database. Every
read, write, and schema operation is checked against a YAML policy — allow/deny, readonly,
field masking, risk scoring, human approval, audit — **before** it reaches the backend.

```
 AI client ──►  GuardMCP core  ──►  plugin  ──►  MongoDB · PostgreSQL · MySQL
                policy · risk · approval ·
                masking · audit · rate-limit
```

A database-agnostic governance core fronts pluggable backends. MongoDB ships native;
PostgreSQL and MySQL are first-class plugins (optional drivers).

> **Why?** An AI agent with raw DB credentials can read, write, or drop anything. GuardMCP
> adds the security layer a database doesn't have: it masks PII, gates dangerous ops behind
> human approval, enforces deny-by-default access, and writes a tamper-evident audit trail.

---

## Quickstart

```bash
git clone <repo-url> guardmcp && cd guardmcp
pip install -e .
cp policies/example.yaml policies/policy.yaml   # set agent, allowed collections, masks
```

Add to your Claude Desktop config
(`~/Library/Application Support/Claude/claude_desktop_config.json`):

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

Restart Claude Desktop, then ask: _"what can I do here?"_ (`guardmcp_capabilities`) or
_"find user X"_ (sensitive fields come back as `***masked***`).

→ Full walkthrough + gotchas: **[QUICKSTART.md](QUICKSTART.md)** · Docker / server mode &
config reference: **[INSTALL.md](INSTALL.md)**.

> Three things that trip people up: use the **absolute** Python path (Claude Desktop's PATH
> won't resolve a shim); `GUARDMCP_AGENT` must equal the policy `agent:`; networked
> transports require `GUARDMCP_APPROVAL_API_TOKEN`.

---

## Tools

63 MCP tools (27 `db_*`, dual-named with `mongodb_*` aliases, + 9 `guardmcp_*` meta).
Capability-neutral `db_*` names are primary; `mongodb_*` aliases are kept for compatibility.
Uniform `{ok, data, error, meta}` envelope; destructive tools are annotated.

| Group | Tools |
|-------|-------|
| **Read** | `db_find` · `db_count` · `db_aggregate` · `db_aggregate_db` · `db_explain` · `db_export` |
| **Discovery** | `db_schema` · `db_indexes` · `db_list_collections` · `db_list_databases` · `db_stats` · `db_collection_storage_size` · `db_logs` · `db_list_connections` · `db_switch_connection` |
| **Write** (readonly-blocked, approval-gated) | `db_insert_one/many` · `db_update_one/many` · `db_delete_one/many` · `db_create_index` · `db_drop_index` · `db_create_collection` · `db_rename_collection` · `db_drop_collection` |
| **Governance** | `guardmcp_status` · `guardmcp_capabilities` · `guardmcp_plan` · `guardmcp_plan_query` · `guardmcp_relationships` · `guardmcp_context` · `guardmcp_setup` · `guardmcp_explain_policy` · `guardmcp_simulate_policy` |

`db_aggregate_db` is DATABASE-level aggregation ($currentOp/$changeStream/$documents/etc — server
introspection, NOT collection data; $currentOp shows every connection's running ops, $changeStream
is bounded to a short best-effort window, not a persistent watch). `db_export` writes an
already-masked find/aggregate result to a local file (`GUARDMCP_EXPORT_DIR`) instead of returning it
inline, for bulk reads. Deliberately NOT provided: an ad-hoc `connect` (arbitrary URI) tool or a
`drop-database` tool — both would let an agent bypass the pre-registered-connection policy boundary.

`guardmcp_capabilities` (_what may I do?_) and `guardmcp_plan` (_what would this do — without
executing?_) let an agent plan deterministically instead of trial-and-error.

---

## Policy

```yaml
agent: claude            # must match GUARDMCP_AGENT
mode: readonly           # readonly | readwrite

collections:
  allow: [customers, orders]   # deny-by-default: omit/empty = DENY-ALL; ["*"] = all
  deny:  [payroll]             # deny always wins

mask_fields:               # flat list, or {collection: [...], "*": [...]}; dotted paths OK
  - password
  - contact.email

approval:                  # readwrite gates
  high: true               # update_*, delete_one, drop_index
  critical: true           # delete_many, drop
```

Also: `extends` (role inheritance), `not_before`/`not_after` (temporal), `fields_allow`
(result projection), `connections_allow`. One file, multiple `agents:`, or a directory of
policies (hot-reloaded). See `policies/example.yaml`.

---

## Configuration

Environment variables, prefix `GUARDMCP_`. Most-used:

| Variable | Default | Notes |
|----------|---------|-------|
| `GUARDMCP_AGENT` | `default-agent` | must match policy `agent:` |
| `GUARDMCP_MONGODB_URI` / `_DATABASE` | `localhost:27017` / `guardmcp` | default connection |
| `GUARDMCP_POLICY_PATH` | `policies/policy.yaml` | file or directory; absolute for stdio |
| `GUARDMCP_TRANSPORT` | `stdio` | `stdio` · `sse` · `streamable-http` |
| `GUARDMCP_APPROVAL_API_TOKEN` | — | **required** for networked transports |
| `GUARDMCP_AUDIT_HMAC_SECRET` | — | enables the tamper-evident audit chain |

Full reference (security, audit, multi-backend, tuning): **[INSTALL.md#configuration](INSTALL.md#configuration)**.

---

## Multiple backends

```bash
pip install -e ".[postgres,mysql]"
export GUARDMCP_CONNECTIONS='{"analytics":{"type":"postgres","dsn":"postgresql://…","database":"app"}}'
```

The same governance applies to every backend; a backend rejects capabilities it doesn't
support (e.g. `aggregate` on SQL) with `UNSUPPORTED_CAPABILITY`.

---

## CLI

`guardmcp` doubles as an operator/CI tool (bare invocation still runs the server):

```bash
guardmcp doctor                     # readiness report
guardmcp policy lint policies/ --strict   # validate + flag dangerous policies (CI)
guardmcp audit verify <log> --secret <s>  # verify the HMAC audit chain (CI)
```

`policy lint` and `audit verify` exit nonzero on failure. Run `guardmcp --help` for all.

---

## Documentation

| | |
|--|--|
| 5-minute setup | [QUICKSTART.md](QUICKSTART.md) |
| Install · Docker · backends · full config | [INSTALL.md](INSTALL.md) |
| Architecture (interfaces, request flow) | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| Write a backend plugin | [docs/PLUGIN_AUTHORS.md](docs/PLUGIN_AUTHORS.md) |
| Security model & reporting | [SECURITY.md](SECURITY.md) |
| Changes | [CHANGELOG.md](CHANGELOG.md) |

---

## Development

```bash
pip install -e ".[dev]"
pre-commit install
python -m pytest -q                   # unit + integration + adversarial (mongomock, no real DB)
python -m guardmcp.eval evals/cases/  # policy/security eval suite
ruff check src/ tests/ && python -m mypy src/guardmcp
```

Live-backend tests (real PG/MySQL/Mongo via Docker, skipped without it):
`pip install -e ".[test-live]" && python -m pytest -m integration`.
See [CONTRIBUTING.md](CONTRIBUTING.md).

---

MIT licensed — see [LICENSE](LICENSE).
