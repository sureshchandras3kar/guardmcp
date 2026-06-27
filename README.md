# GuardMCP

**Policy-enforced MongoDB MCP server. AI proposes. GuardMCP decides.**

GuardMCP sits between any MCP client (Claude Desktop, Cursor, OpenAI Agents) and your MongoDB instance. Every query, write, and schema operation is evaluated against a YAML policy before it reaches the database.

```
AI Client ──► GuardMCP ──► MongoDB
               (policy, masking,
                audit, approval)
```

---

## Features

| Capability | Detail |
|---|---|
| **Action allow/deny** | Per-agent allow/deny lists for every MongoDB operation |
| **Collection allow/deny** | Restrict which collections an agent can touch |
| **Readonly mode** | Block all writes at the policy layer |
| **Field masking** | Strip sensitive fields from every result — applied recursively |
| **Operator blocking** | `$where`, `$function`, `$accumulator`, `$out`, `$merge` blocked at parse time |
| **Risk scoring** | Every action classified LOW → CRITICAL |
| **Human approval** | In-band `ctx.elicit()` confirmation for HIGH/CRITICAL ops |
| **Audit log** | Async append-only JSONL — every request, decision, and outcome |
| **Cursor pagination** | `skip + limit` with `has_more` / `next_skip` |
| **Schema inference** | Infer field types from sample docs; masked fields shown as `"masked"` |
| **Index introspection** | List all indexes including vector search |
| **Explain plans** | Query execution plan + index usage |
| **Multiple connections** | Switch between named MongoDB URIs at runtime |
| **maxTimeMS** | Per-query timeout enforced server-side |
| **Index scan enforcement** | Optional: block queries with no covering index |

---

## Quickstart

### Option A — Docker Compose (recommended)

```bash
git clone https://github.com/your-org/guardmcp
cd guardmcp

# Copy and edit the example policy
cp policies/example.yaml policies/policy.yaml
$EDITOR policies/policy.yaml   # set agent name, allowed collections, mask_fields

docker compose up
```

MCP endpoint: `http://localhost:8000/mcp`
Approval REST API: `http://localhost:8001`

---

### Option B — pip + stdio (Claude Desktop)

```bash
pip install guardmcp
mkdir -p policies logs
cp policies/example.yaml policies/policy.yaml
# Edit policies/policy.yaml — set agent name, collections, mask_fields
```

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "guardmcp": {
      "command": "python",
      "args": ["-m", "guardmcp"],
      "env": {
        "GUARDMCP_AGENT": "my-agent",
        "GUARDMCP_MONGODB_URI": "mongodb://localhost:27017",
        "GUARDMCP_MONGODB_DATABASE": "mydb",
        "GUARDMCP_POLICY_PATH": "/absolute/path/to/policies/policy.yaml",
        "GUARDMCP_AUDIT_LOG_PATH": "/absolute/path/to/logs/audit.jsonl"
      }
    }
  }
}
```

Restart Claude Desktop. GuardMCP tools appear automatically.

> `GUARDMCP_AUDIT_LOG_PATH` is optional. If you omit it, the audit log defaults
> to a per-user state directory (`~/Library/Logs/guardmcp/audit.jsonl` on macOS
> — see [Audit Log](#audit-log)). Setting an explicit absolute path as shown
> above still works and is recommended when you want the log in a known place.

---

## Policy File

```yaml
# policies/policy.yaml

agent: my-agent          # must match GUARDMCP_AGENT env var

mode: readonly           # readonly | readwrite

collections:
  allow:
    - customers
    - orders
  deny:
    - payroll            # deny beats allow

actions:
  allow:
    - find
    - count
    - aggregate
    - collection_schema
    - collection_indexes
    - list_databases
    # readwrite mode: also add insert_one, update_one, delete_one, etc.

# Stripped from every result before returning to the AI client.
# Applied recursively — nested fields (e.g. contact.email) are masked too.
mask_fields:
  - email
  - password
  - phone
  - ssn
  - credit_card

# Require human confirmation for risky ops (readwrite mode only)
approval:
  high: true      # update_one, update_many, delete_one, drop_index
  critical: true  # delete_many, drop
```

### Multi-agent setup

Put multiple policies in one file under `agents:`:

```yaml
agents:
  - agent: support-bot
    mode: readonly
    collections:
      allow: [customers, tickets]
    mask_fields: [email, phone]

  - agent: data-pipeline
    mode: readwrite
    collections:
      allow: [staging, archive]
    approval:
      high: true
      critical: true
```

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `GUARDMCP_MONGODB_URI` | `mongodb://localhost:27017` | MongoDB connection URI |
| `GUARDMCP_MONGODB_DATABASE` | `guardmcp` | Default database name |
| `GUARDMCP_AGENT` | `default-agent` | Agent identity — set by operator, never by AI |
| `GUARDMCP_POLICY_PATH` | `policies/policy.yaml` | Path to policy YAML |
| `GUARDMCP_AUDIT_LOG_PATH` | platform state dir (see [Audit Log](#audit-log)) | Audit log output path. Absolute path wins (e.g. a Docker volume); relative is resolved under the per-user state dir, never cwd. |
| `GUARDMCP_TRANSPORT` | `stdio` | `stdio` \| `sse` \| `streamable-http` |
| `GUARDMCP_HOST` | `127.0.0.1` | Bind host (HTTP transports) |
| `GUARDMCP_PORT` | `8000` | MCP server port |
| `GUARDMCP_APPROVAL_PORT` | `8001` | Approval REST API port |
| `GUARDMCP_MAX_TIME_MS` | `30000` | Per-query timeout ms (0 = unlimited) |
| `GUARDMCP_ENFORCE_INDEX_USAGE` | `false` | Block queries with no covering index |
| `GUARDMCP_SCHEMA_SAMPLE_SIZE` | `20` | Docs sampled for `collection_schema` |
| `GUARDMCP_APPROVAL_TIMEOUT_SECONDS` | `300` | Seconds to wait for human approval |
| `GUARDMCP_APPROVAL_API_TOKEN` | `` | Token for `X-Approval-Token` header (empty = no auth, stdio-only safe) |
| `GUARDMCP_INBAND_CONFIRM` | `true` | `ctx.elicit()` in-band approval vs REST out-of-band |
| `GUARDMCP_EXTRA_CONNECTIONS__staging` | — | Extra named MongoDB URI |

---

## MCP Tools

### Discovery
| Tool | Description |
|---|---|
| `mongodb_list_collections` | Collections the agent can access per policy |
| `mongodb_collection_schema` | Infer field types from sample docs |
| `mongodb_collection_indexes` | All indexes including vector search |
| `mongodb_list_databases` | All databases on the server |
| `mongodb_db_stats` | Database statistics |
| `mongodb_explain` | Query execution plan + index usage |
| `mongodb_list_connections` | Named connections registered at startup |
| `mongodb_switch_connection` | Swap active MongoDB connection |

### Read
| Tool | Description |
|---|---|
| `mongodb_find` | Find docs with filter, projection, sort, skip+limit pagination |
| `mongodb_count` | Count matching documents |
| `mongodb_aggregate` | Aggregation pipeline (write stages blocked) |

### Write (blocked in readonly mode)
| Tool | Description |
|---|---|
| `mongodb_insert_one` | Insert one document |
| `mongodb_insert_many` | Insert multiple documents |
| `mongodb_update_one` | Update first matching document |
| `mongodb_update_many` | Update all matching documents |
| `mongodb_delete_one` | Delete first matching document |
| `mongodb_delete_many` | Delete all matching documents |
| `mongodb_create_index` | Create regular or vector search index |
| `mongodb_drop_index` | Drop index by name |

### Governance (meta tools)
| Tool | Description |
|---|---|
| `guardmcp_status` | Connection status, DB stats, version, policy summary |
| `guardmcp_setup` | Interactive policy wizard (writes + hot-reloads policy.yaml) |
| `guardmcp_capabilities` | Backend + per-collection permitted actions |
| `guardmcp_plan` | Dry-run: decision / risk / approval / affected-estimate / **normalized query cost** (best-effort, never the raw explain), no execution |
| `guardmcp_explain_policy` | Why a (agent, collection, action) is allowed/denied/needs-approval — ordered rule trace from the real evaluator (read-only) |
| `guardmcp_simulate_policy` | What-if: evaluate a request against current vs proposed policy, diff the rules, rate security impact — never persisted or executed (read-only) |

---

## Human Approval Workflow

When policy has `approval: { high: true }`, HIGH-risk operations pause and ask for confirmation.

**In-band (default):**
Claude Desktop shows a confirmation dialog in the chat. No external process needed.

**Out-of-band (`GUARDMCP_INBAND_CONFIRM=false`):**

```bash
# List pending approvals
curl -H "X-Approval-Token: $GUARDMCP_APPROVAL_API_TOKEN" \
     http://localhost:8001/approvals/pending

# Approve
curl -X POST \
     -H "Content-Type: application/json" \
     -H "X-Approval-Token: $GUARDMCP_APPROVAL_API_TOKEN" \
     -d '{"approved": true}' \
     http://localhost:8001/approvals/{id}/decide
```

> Set `GUARDMCP_APPROVAL_API_TOKEN` for any non-stdio deployment. Empty = no auth.

---

## Audit Log

Every request writes a JSONL record:

```json
{
  "timestamp": "2026-06-24T10:00:00Z",
  "agent": "support-bot",
  "collection": "customers",
  "action": "find",
  "status": "allowed",
  "reason": "request permitted by policy.",
  "risk": "LOW",
  "request_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

Audit writes are async (non-blocking). Write failures are logged to stderr and
never fail the request (unless `GUARDMCP_AUDIT_FAIL_CLOSED=true`).

### Where the audit log goes

The audit log is written to a **platform-appropriate per-user state directory**,
resolved to an **absolute path at startup** (never cwd-relative — stdio clients
often launch with `cwd=/`). GuardMCP logs the resolved path under the
`audit_log_path` event at startup so you can see exactly where it lands.

| Platform | Default location |
| --- | --- |
| macOS | `~/Library/Logs/guardmcp/audit.jsonl` |
| Linux | `$XDG_STATE_HOME/guardmcp/audit.jsonl`, else `~/.local/state/guardmcp/audit.jsonl` |
| Windows | `%LOCALAPPDATA%\guardmcp\logs\audit.jsonl` |

Override with `GUARDMCP_AUDIT_LOG_PATH`:

- An **absolute** path is used as-is (operator/Docker control).
- A **relative** path is resolved under the state dir above — *not* the current
  working directory — so a stray relative path can never land in `/` or your
  repo checkout.

If the resolved directory is not writable, GuardMCP **fails loud at startup**
with an actionable error (it does not crash mid-request), which matters with
`GUARDMCP_AUDIT_FAIL_CLOSED=true`.

**Docker / containers:** mount a volume and point the audit log at it:

```bash
docker run -v /host/guardmcp-audit:/var/log/guardmcp \
  -e GUARDMCP_AUDIT_LOG_PATH=/var/log/guardmcp/audit.jsonl \
  guardmcp
```

Alternatively, set `XDG_STATE_HOME` (POSIX) to relocate the whole state dir, or
implement `AuditSinkProtocol` (`core/interfaces/stores.py`) to ship records to a
centralized append-only audit store.

> **Structured application logs** (the JSON `log_event` lines, including the
> startup `audit_log_path` event) go to **stderr**, not to a file. Only the
> audit JSONL records described above are written to the audit log path.

---

## Multiple MongoDB Connections

Register extra named connections at startup:

```bash
GUARDMCP_EXTRA_CONNECTIONS__staging=mongodb://staging:27017/mydb
GUARDMCP_EXTRA_CONNECTIONS__prod=mongodb://prod:27017/mydb
```

The AI can call `mongodb_switch_connection("staging")` to swap (subject to policy).

---

## Security Model

| Defense | Implementation |
|---|---|
| Agent identity | Set by operator via `GUARDMCP_AGENT` — AI client cannot override |
| Operator injection | `$where`, `$function`, `$accumulator` blocked recursively in filters and pipelines |
| Write-stage bypass | `$out`, `$merge` blocked in aggregation pipelines |
| Field masking | Recursive — `contact.email` masked if `email` is in `mask_fields` |
| Error leakage | Raw MongoDB errors sanitized before reaching AI |
| Result flood | Hard cap: 500 documents max regardless of AI request |
| Approval bypass | REST approval API requires `X-Approval-Token` when configured |
| TOCTOU | Policy re-evaluated after elicit wait before execution |

---

## Development

```bash
git clone https://github.com/your-org/guardmcp
cd guardmcp
pip install -e ".[dev]"
pytest
```

104 tests, no real MongoDB required (mongomock-motor).

---

## License

MIT
