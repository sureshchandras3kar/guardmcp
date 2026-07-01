# GuardMCP — Quickstart

Get GuardMCP governing a MongoDB in ~5 minutes, connected to Claude Desktop.

> GuardMCP sits between an AI agent and your database. The AI proposes queries;
> GuardMCP enforces a YAML policy (allow/deny, readonly, masking, approval, audit)
> before anything reaches the DB.

---

## Prerequisites

- **Python 3.12+**
- A running **MongoDB** (local: `mongodb://localhost:27017`)
- **Claude Desktop** (or any MCP client)

---

## 1. Install

```bash
git clone <repo-url> guardmcp
cd guardmcp
pip install -e .
```

Verify:

```bash
python -c "import guardmcp; print('ok')"
```

---

## 2. Create a policy

A policy says what an agent may do. Start from the example:

```bash
cp policies/example.yaml policies/policy.yaml
$EDITOR policies/policy.yaml
```

Minimum to know:

```yaml
agent: claude              # MUST match GUARDMCP_AGENT below
mode: readonly             # readonly blocks all writes
collections:
  allow: [users, orders]   # deny-by-default: empty/omitted = DENY-ALL; use ["*"] for all
  deny:  [payroll]         # deny always wins
mask_fields:               # stripped from every result
  - password
  - email
```

> **Deny-by-default:** if you omit `collections.allow`, **no collection is accessible**.
> Use `allow: ["*"]` to permit all. This is intentional — a governance tool fails closed.

Preview a policy decision without any DB call:

```bash
# (after connecting — via the guardmcp_explain_policy / guardmcp_plan tools)
```

---

## 3. Connect Claude Desktop (stdio)

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`
(Linux: `~/.config/Claude/`, Windows: `%APPDATA%\Claude\`):

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

**Critical — must follow:**
- `command` MUST be the **absolute** path to the Python that has guardmcp installed
  (`python -c "import sys; print(sys.executable)"`). Claude Desktop launches with a
  minimal PATH and will not resolve a bare `python` / pyenv shim.
- `GUARDMCP_AGENT` MUST equal the policy's `agent:` field — that's how GuardMCP picks
  the policy. Mismatch → every request denied ("no policy for agent").
- `GUARDMCP_POLICY_PATH` should be **absolute** (stdio launches with `cwd=/`).
- Audit log defaults to a per-user location (macOS `~/Library/Logs/guardmcp/`,
  Linux `$XDG_STATE_HOME/guardmcp/`, Windows `%LOCALAPPDATA%\guardmcp\logs\`).
  Override with `GUARDMCP_AUDIT_LOG_PATH=/abs/path`.

**Fully quit and reopen Claude Desktop** (Cmd+Q — not just close the window) so it
reloads the config.

---

## 4. Try it

In Claude:

1. *"call guardmcp_status"* → connection banner + DB stats + policy summary.
2. *"what can I do here?"* → `guardmcp_capabilities` (per-collection permitted actions).
3. *"list my collections"* → only policy-permitted collections.
4. *"find user X"* → masked fields come back as `***masked***`.
5. *"what would deleting all users do?"* → `guardmcp_plan` (dry-run: decision, risk,
   approval, affected estimate — **does not execute**).

Every call is written to the audit log.

---

## 5. Verify the install (optional)

```bash
pip install -e ".[dev]"
python -m pytest -q                 # 546 passed
python -m guardmcp.eval evals/cases/ # 38/38 passed
```

---

## Next

- **Docker / server mode (SSE / streamable-http):** see [INSTALL.md](INSTALL.md)
- **PostgreSQL / MySQL backends:** see [INSTALL.md](INSTALL.md#backends)
- **All config / env vars:** see [INSTALL.md](INSTALL.md#configuration)
- **Feature inventory:** see [README.md](README.md#features-overview) and [CHANGELOG.md](CHANGELOG.md#added)
- **Writing a plugin:** see [docs/PLUGIN_AUTHORS.md](docs/PLUGIN_AUTHORS.md)
