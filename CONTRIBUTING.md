# Contributing to GuardMCP

Thanks for contributing. GuardMCP is a policy-enforced MCP database server: AI
proposes operations, GuardMCP decides. This guide covers local setup, the test
gates, and the rules that keep the architecture clean.

## Dev setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Optional backend drivers (only needed to run those backends live):

```bash
pip install -e ".[postgres]"   # asyncpg
pip install -e ".[mysql]"      # aiomysql
```

## Code quality

GuardMCP standardizes on **Ruff** (lint + formatter + import sorting) and
**mypy** (pragmatic type-checking), configured once in `pyproject.toml`.

```bash
pip install -e ".[dev]"   # installs ruff, mypy, pre-commit
pre-commit install        # run the hooks automatically on every commit

# Or run them by hand:
ruff check src/ tests/          # lint (add --fix to auto-fix)
ruff format src/ tests/         # format (add --check to verify only)
mypy src/guardmcp               # type-check (src only)
pytest                          # tests
```

All four are blocking in CI. The pre-commit hooks mirror them, so a clean
`pre-commit run --all-files` means CI will pass.

## Running the gates

All three must pass before a PR is merged:

```bash
# Unit + integration tests (includes conformance under tests/conformance/)
python -m pytest

# Conformance kit only (the three builtins against the plugin contract)
python -m pytest tests/conformance/

# Evals — behavioural policy/governance cases
python -m guardmcp.eval evals/cases/
```

The eval suite must report **all cases passed**; the test suite must stay green.

### Live-backend integration tests

`tests/integration/test_live_backends.py` spins **real** PostgreSQL, MySQL, and
MongoDB containers (via [`testcontainers`](https://testcontainers.com)) and
drives them through the actual `asyncpg` / `aiomysql` / `motor` drivers — proving
the translation + execution path end-to-end (the rest of the suite uses
mongomock). They are marked `integration`:

```bash
pip install -e ".[test-live,postgres,mysql]"   # testcontainers + drivers
pytest -m integration                            # run ONLY the live tests
```

These tests are included in a normal `pytest` run but **SKIP cleanly** when
`testcontainers` is not installed or Docker is unavailable — they never fail or
error a Docker-less CI.

## Code layout

```
src/guardmcp/
  core/         # database-AGNOSTIC: interfaces, registry, policy/risk/approval/
                # audit/mask governance, domain models
  conformance/  # shipped plugin conformance kit (importable by plugin authors)
  plugins/      # backend plugins: mongodb/, postgres/, mysql/
  server/       # MCP server / tool layer
```

## The dependency rule

**Core never imports plugins.** `core/` is backend-agnostic and must not depend on
`plugins/`. Plugins depend on `core` (the interfaces, capabilities, errors), never
the other way around. Plugins are wired in only via the `guardmcp.plugins`
entry-point group and the `PluginRegistry`. PRs that introduce a `core → plugin`
import will be rejected.

## Adding a backend plugin

See **[docs/PLUGIN_AUTHORS.md](docs/PLUGIN_AUTHORS.md)** for the full contract,
security requirements, and registration. In short: implement `DatabasePlugin`,
parameterize all values, validate identifiers, report cross-resource refs, and
verify with the conformance kit:

```python
from guardmcp.conformance import assert_plugin_conformant
assert_plugin_conformant(MyPlugin())                                # any backend
assert_plugin_conformant(MyPlugin(), expects_identifier_validation=True)  # SQL-style
```

## PR expectations

- `python -m pytest` is green and `python -m guardmcp.eval evals/cases/` passes.
- New plugins ship conformance tests (`assert_plugin_conformant`).
- No `core → plugin` imports.
- Values are parameterized; identifiers are validated; no raw-SQL escape hatch.
- Update `CHANGELOG.md` under `Unreleased`.
