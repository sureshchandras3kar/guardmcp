# AGENTS.md — GuardMCP

Cross-tool agent context (Claude Code, Codex, Copilot, Cursor, Gemini, etc.).
The canonical, detailed context lives in **`CLAUDE.md`** — read it. This file
mirrors the essentials so non-Claude tools have them too.

## What this is
GuardMCP (Python ≥3.12, `v0.0.1a1`): a **deterministic (no-LLM)** MCP server that
**governs** database access (policy · risk · approval · masking · audit) and
supplies **database intelligence** (query planning, relationship + cross-database
join-key discovery, field semantics). *AI proposes; GuardMCP decides, masks,
audits, advises.* Full backend: MongoDB; partial: PostgreSQL/MySQL.

## Non-negotiable rules
1. No AI/LLM logic in `core/`; everything deterministic.
2. No backend dialect (Mongo/SQL) in `core/` — it lives in `plugins/`.
3. Data-agnostic: no hardcoded collection/field/product names.
4. New params optional + trailing (backward compatible).
5. Deny-by-default; masked fields never sampled/emitted.
6. Test fakes must mirror REAL callee signatures (lenient `**kwargs` fakes have
   hidden real bugs).
7. Verify from a clean tree: `git status` clean + full suite + eval before trusting.

## Commands (use the venv; `python` is not on PATH)
```bash
.venv/bin/python -m pytest -q --deselect tests/integration/test_transport_lifecycle.py::test_streamable_http_db_tool_survives_session_boundary
.venv/bin/python -m guardmcp.eval evals/cases/     # 42/42
.venv/bin/python -m ruff check src tests
```

## Golden path
`server/tools/*` → `GuardPipeline.run` → `evaluate` (policy+risk, no execution) →
approve → execute (plugin) → mask → audit. Context-Engine tools are advisory and
never execute.

## Reference docs
- `CLAUDE.md` — full working context (canonical).
- `docs/PROJECT_SSOT.md` — single source of truth (architecture → roadmap).
- `docs/FEATURE_STATUS.md` — completed / in-progress / not-started.
- `docs/PLUGIN_AUTHORS.md`, `docs/ARCHITECTURE.md`, `SECURITY.md`.

## When unsure
Mark Unknown / Assumption / Needs Verification / Not Yet Implemented — never invent.
