# CLAUDE.md — GuardMCP project context for AI assistants

> Read this first. It is the working context for any AI assistant editing this repo.
> Authoritative deep reference: **`docs/PROJECT_SSOT.md`**. Feature status:
> **`docs/FEATURE_STATUS.md`**. Backend contract: `docs/PLUGIN_AUTHORS.md`.
> Architecture: `docs/ARCHITECTURE.md`. Design/plan history: `docs/superpowers/`.

## What this is
GuardMCP (`v0.0.1a1`, Python ≥3.12): a **deterministic (no-LLM)** MCP server that
**governs** database access (policy · risk · approval · masking · audit) and
provides **database intelligence** (planning, relationships, field semantics,
cross-DB join keys). **The AI proposes; GuardMCP decides, masks, audits, and
advises.** MongoDB is the full backend; PostgreSQL/MySQL are partial plugins.

## Golden path (never bypass)
tool (`server/tools/*`) → `GuardPipeline.run()` (`core/pipeline.py`) →
`evaluate()` (policy+risk, **no execution**) → approve (in-band elicit OR REST) →
execute (plugin) → mask + neutral view → audit (HMAC JSONL). Context-Engine tools
(`guardmcp_plan_query`, `guardmcp_relationships`) are **advisory**: they read only
**governed** metadata and **never execute**.

## Hard rules (violating these has caused real bugs)
1. **No AI/LLM logic in `core/`.** Everything deterministic.
2. **No backend dialect in `core/`.** Mongo/SQL specifics live in `plugins/`.
   `core` never imports a concrete backend; plugins depend on `core.interfaces`.
3. **Data-agnostic.** No hardcoded collection/field/product names. Detection is
   structural + generic conventions; discovered at runtime.
4. **New params are optional + trailing** (backward compatibility is mandatory;
   `database=None` etc.).
5. **`CapabilityRequest` is the portable IR** — don't invent a new one.
6. **Deny-by-default** everywhere; empty `allow` = deny-all; masked fields are
   never sampled/emitted and can't be relationship/alignment endpoints.
7. **Test fakes MUST mirror the REAL callee signatures.** Lenient `**kwargs` fakes
   hid two committed-code blockers (a tool passed a kwarg the real callee rejected;
   green only because the fake accepted it). Keep/extend
   `tests/unit/test_tool_pipeline_contract.py`.
8. **Verify from a clean tree.** A whole phase once ran "green" on an *uncommitted*
   edit. Always `git status` clean + run the FULL suite + eval before trusting.

## Commands (this machine: use the venv; `python` is NOT on PATH)
```bash
.venv/bin/python -m pytest -q --deselect tests/integration/test_transport_lifecycle.py::test_streamable_http_db_tool_survives_session_boundary
.venv/bin/python -m guardmcp.eval evals/cases/        # expect 42/42
.venv/bin/python -m ruff check src tests
# run server (stdio): GUARDMCP_AGENT=... GUARDMCP_MONGODB_URI=... GUARDMCP_MONGODB_DATABASE=... \
#   GUARDMCP_POLICY_PATH=... GUARDMCP_AUDIT_LOG_PATH=... .venv/bin/python -m guardmcp --transport stdio
```
The `test_streamable_http_db_tool_survives_session_boundary` test is a known flake
(needs a live Mongo / an unfixed Motor-under-HTTP lifecycle bug) — deselect it.

## Key files
- Governance: `core/pipeline.py`, `core/policy/{models,engine,loader}.py`,
  `core/masking/masker.py`, `core/audit/logger.py`, `core/risk/engine.py`,
  `core/registry/*`, `core/validation.py`.
- Contracts: `core/interfaces/{plugin,capability,cost,errors,stores}.py`.
- Backend: `plugins/mongodb/{plugin,executor,schema_cache,guard,relationships}.py`.
- Intelligence: `core/planning/*` (ambiguity, relationships, planner, alternatives,
  recommend, cross_db, cross_db_resolver), `core/context/semantics.py`.
- Surface/wiring: `server/tools/{read,write,_common}.py`, `server/tools/meta/*`,
  `config.py`, `__main__.py`, `api/approval.py`.

## Conventions
- MCP tools are dual-named `db_*` and `mongodb_*`; envelope `{ok,data,error,meta}`.
- Policy field is `resource_schema` (NOT `schema` — shadows pydantic `BaseModel`).
- Roles are strings: `primary_identifier`/`foreign_identifier`/`tenant_key`/
  `timestamp`/`enum_status`/`pii`/`none`. Cross-DB signals: 1=shared-name,
  2=value-overlap, 3=identifier-role alignment.
- Governance enums in `core/models/domain.py` (Action/RiskLevel/DecisionStatus) and
  `core/interfaces/errors.py` (ErrorCode).
- Multi-database: per-`database` policy scope (`databases_allow`/`databases`/
  `default`); a disallowed DB → `DATABASE_NOT_ALLOWED`.

## Workflow (observed)
Feature branches (`feat/…`) off the integration branch
`Task/v0.0.1_guardmcp-alpha_context_build`; brainstorm→spec→plan (`docs/superpowers/`)
→ TDD → per-task + final review → squash-merge. Commit trailer:
`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

## Codebase navigation
A knowledge graph may exist (`graphify-out/`). Prefer `graphify query "<question>"`
to orient before grepping when available; it may be absent in a given shell — then
read files directly.

## When unsure
Mark **Unknown / Assumption / Needs Verification / Not Yet Implemented** rather than
inventing. Check `docs/PROJECT_SSOT.md` §16 (known issues) and §22 (doc gaps).
