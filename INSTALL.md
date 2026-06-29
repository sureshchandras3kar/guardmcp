# GuardMCP — Installation

Covers every install path: pip (stdio), Docker (server), backends, dev, and the
full configuration reference. For the 5-minute path see [QUICKSTART.md](QUICKSTART.md).

---

## Requirements

| | |
|--|--|
| Python | **3.12+** (hard requirement) |
| Database | MongoDB (built-in). PostgreSQL / MySQL via optional extras. |
| OS | macOS · Linux · Windows |

---

## A. pip (local / stdio — Claude Desktop, Cursor, …)

```bash
git clone <repo-url> guardmcp
cd guardmcp
pip install -e .                      # core (MongoDB) only
```

Console entry points (installed by pip):

| Command | Equivalent |
|---------|-----------|
| `guardmcp` | `python -m guardmcp` |
| `guardmcp-eval` | `python -m guardmcp.eval` |

> If `guardmcp-eval` isn't on PATH (shim not regenerated), use
> `python -m guardmcp.eval` — always works.

Run the server (stdio):

```bash
GUARDMCP_AGENT=claude \
GUARDMCP_MONGODB_URI=mongodb://localhost:27017 \
GUARDMCP_MONGODB_DATABASE=mydb \
GUARDMCP_POLICY_PATH=$PWD/policies/policy.yaml \
python -m guardmcp --transport stdio
```

stdio mode opens **no network port** — it talks over stdin/stdout and is meant to be
spawned by an MCP client (see [QUICKSTART.md](QUICKSTART.md#3-connect-claude-desktop-stdio)).

---

## B. Docker (server mode — SSE / streamable-http)

```bash
docker compose up --build
```

This starts MongoDB + GuardMCP. **MCP endpoint:** `http://localhost:8000` ·
**Approval API:** `http://localhost:8001`.

> ### ⚠ Must follow — networked transports require an approval token
> `sse` and `streamable-http` expose the approval REST API on a TCP port. GuardMCP
> **refuses to start** on these transports unless you set `GUARDMCP_APPROVAL_API_TOKEN`
> (any local process could otherwise approve CRITICAL writes). The shipped
> `docker-compose.yml` sets a placeholder token — **change it** before any real use.
> For local-only experimentation you may instead set
> `GUARDMCP_APPROVAL_ALLOW_INSECURE=true` (NOT for production).

Mounts (from `docker-compose.yml`): `./policies` (read-only) and `./logs`.
Set the audit path to the mounted volume in production:
`GUARDMCP_AUDIT_LOG_PATH=/app/logs/audit.jsonl`.

---

## C. Backends (PostgreSQL / MySQL) {#backends}

Optional drivers — install only what you use:

```bash
pip install -e ".[postgres]"   # asyncpg
pip install -e ".[mysql]"      # aiomysql
pip install -e ".[postgres,mysql]"
```

Declare typed connections via `GUARDMCP_CONNECTIONS` (JSON). The default MongoDB
connection (from `GUARDMCP_MONGODB_URI`) is always present:

```bash
export GUARDMCP_CONNECTIONS='{
  "analytics": {"type": "postgres", "dsn": "postgresql://user:pass@host/db",
                "database": "app", "options": {"min_size": 1, "max_size": 10}},
  "reporting": {"type": "mysql", "dsn": "mysql://user:pass@host/db"}
}'
```

Switch at runtime with the `switch_connection` tool (policy-gated via
`connections_allow`). A backend rejects capabilities it doesn't support (e.g.
`aggregate` on SQL) with `UNSUPPORTED_CAPABILITY`.

---

## D. Development

```bash
pip install -e ".[dev]"
pre-commit install            # ruff + mypy on every commit

python -m pytest -q                  # unit + integration + adversarial
python -m guardmcp.eval evals/cases/ # policy/security eval suite
ruff check src/ tests/ && ruff format --check src/ tests/
python -m mypy src/guardmcp
```

Live-backend tests (real PG/MySQL/Mongo via Docker; **skip cleanly without Docker**):

```bash
pip install -e ".[test-live]"
python -m pytest -m integration
```

---

## Configuration {#configuration}

All settings are environment variables, prefix `GUARDMCP_`.

### Core
| Var | Default | Notes |
|-----|---------|-------|
| `GUARDMCP_AGENT` | `default-agent` | **Must match** the policy `agent:` field |
| `GUARDMCP_MONGODB_URI` | `mongodb://localhost:27017` | default connection |
| `GUARDMCP_MONGODB_DATABASE` | `guardmcp` | |
| `GUARDMCP_POLICY_PATH` | `policies/policy.yaml` | file **or directory** of policies; use an absolute path for stdio |
| `GUARDMCP_TRANSPORT` | `stdio` | `stdio` · `sse` · `streamable-http` |
| `GUARDMCP_HOST` / `GUARDMCP_PORT` | `127.0.0.1` / `8000` | network transports |
| `GUARDMCP_APPROVAL_PORT` | `8001` | approval REST API |

### Security
| Var | Default | Notes |
|-----|---------|-------|
| `GUARDMCP_APPROVAL_API_TOKEN` | `""` | **required** for `sse`/`streamable-http` (else server refuses to start) |
| `GUARDMCP_APPROVAL_ALLOW_INSECURE` | `false` | local-only override of the above (NOT for prod) |
| `GUARDMCP_AUDIT_HMAC_SECRET` | `""` | set → tamper-evident HMAC audit chain |
| `GUARDMCP_AUDIT_FAIL_CLOSED` | `false` | true → abort an op if its audit record can't be written |

### Audit & logging
| Var | Default | Notes |
|-----|---------|-------|
| `GUARDMCP_AUDIT_LOG_PATH` | platform state dir¹ | absolute path / Docker volume |
| `GUARDMCP_NODE_ID` | `""` | set a unique id per replica (multi-instance) |
| `GUARDMCP_LOG_LEVEL` | `info` | `debug`·`info`·`warning`·`error` (structured JSON → stderr) |

¹ macOS `~/Library/Logs/guardmcp/audit.jsonl` · Linux `$XDG_STATE_HOME/guardmcp/` (→ `~/.local/state/guardmcp/`) · Windows `%LOCALAPPDATA%\guardmcp\logs\`.

### Multi-backend / tuning
| Var | Default | Notes |
|-----|---------|-------|
| `GUARDMCP_CONNECTIONS` | `{}` | JSON typed connections (see [Backends](#backends)) |
| `GUARDMCP_APPROVAL_TIMEOUT_SECONDS` | `300` | approval times out → **deny** |
| `GUARDMCP_RATE_LIMIT_RPS` / `_BURST` | `0` / `10` | per-agent token bucket (0 = off) |
| `GUARDMCP_MAX_TIME_MS` | `30000` | per-query timeout |
| `GUARDMCP_SCHEMA_CACHE_TTL` | `300` | schema-inference cache (0 = off) |

---

## Verifying a healthy install

```bash
# 1. import
python -c "import guardmcp; print('ok')"

# 2. server starts + lists tools (stdio)
GUARDMCP_AGENT=claude GUARDMCP_POLICY_PATH=$PWD/policies/example.yaml \
  python -m guardmcp --transport stdio   # then send an MCP initialize/tools-list

# 3. suites
python -m pytest -q
python -m guardmcp.eval evals/cases/
```

For a misconfigured policy or unwritable audit path, GuardMCP **fails loud at startup**
with an actionable message (not a traceback).

---

## CLI / operations

The `guardmcp` entry point is also an operator/CI CLI. Bare `guardmcp` and any
`--transport …` flag still start the server (back-compat); the subcommands below are
additive. Each has its own `--help` (e.g. `guardmcp policy lint --help`).

| Command | Args | Exit codes |
| --- | --- | --- |
| `guardmcp version` | — | always `0`. Reads installed package metadata (stale? `pip install -e .`). |
| `guardmcp doctor` | — | `0` PASS / `1` FAIL. DB unreachable → WARN, still `0`. |
| `guardmcp config validate` | — | `0` PASS / `1` FAIL (H1, audit path). No DB call. |
| `guardmcp policy lint <path>` | `[--strict]` | `0` clean (warnings allowed) / `1` on schema error, or any warning under `--strict`. |
| `guardmcp audit verify <log>` | `--secret <s>` (or `GUARDMCP_AUDIT_HMAC_SECRET`) | `0` verified · `1` chain broken (prints first bad line) · `2` read error · `3` not verifiable (no `_hmac`/no secret). |
| `guardmcp capability inspect <type>` | `[--format text\|json]` | `0` / `1` if the type is unknown. |

```bash
guardmcp doctor
guardmcp policy lint policies/ --strict
guardmcp audit verify "$GUARDMCP_AUDIT_LOG_PATH" --secret "$GUARDMCP_AUDIT_HMAC_SECRET"
```

**Health endpoints (networked transports):** on `sse`/`streamable-http`, the approval API
serves `/healthz` (liveness, always 200) and `/readyz` (200 when policy is loaded and the
default backend is reachable, else 503) on the approval port (`GUARDMCP_APPROVAL_PORT`,
default 8001). Wire these to Kubernetes liveness/readiness probes. `/health` and `/ready`
are kept as aliases.

---

## Checklist before production

- [ ] Explicit `collections.allow` in every policy (never rely on empty = all — it's deny-all, but be explicit)
- [ ] `GUARDMCP_APPROVAL_API_TOKEN` set (networked transports)
- [ ] `GUARDMCP_AUDIT_HMAC_SECRET` set (tamper-evident audit)
- [ ] `GUARDMCP_AUDIT_LOG_PATH` on durable storage (volume), not the repo
- [ ] `GUARDMCP_NODE_ID` unique per replica
- [ ] `approval.high` / `approval.critical` enabled for write agents
- [ ] Run `python -m pytest` + `python -m guardmcp.eval evals/cases/` in CI
