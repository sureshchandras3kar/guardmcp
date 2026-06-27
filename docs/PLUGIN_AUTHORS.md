# Writing a GuardMCP Backend Plugin

This guide is for authors of a new GuardMCP database backend (e.g. SQLite,
ClickHouse, DynamoDB). It explains the `DatabasePlugin` contract, the security
requirements you MUST meet, how to register your plugin, and how to verify it.

## Architecture in one paragraph

GuardMCP's **core** is database-agnostic. It owns all *governance* — policy
evaluation, risk scoring, approval workflows, audit logging, and field masking —
and applies it to every request *before* and *after* a backend touches data. A
**plugin** implements only the mechanics of one backend: translate a generic
`CapabilityRequest` into a safe, parameterized backend operation, run it, and map
the outcome back into a `CapabilityResult`. Plugins never make policy decisions
and never see the policy engine. Your job is to be a *safe, faithful* executor and
to truthfully describe what each request touches so core can authorize it.

## The `DatabasePlugin` contract

`src/guardmcp/core/interfaces/plugin.py` defines the abstract base class. Every
method below is abstract (must be overridden) except `cross_resource_refs`, which
has a safe default (`return set()`) you should override if your backend can reach
secondary resources.

| Member | Kind | Purpose |
| --- | --- | --- |
| `name: str` | attr | Unique backend name (the registry key, e.g. `"postgres"`). Non-empty. |
| `api_version: str` | attr | Plugin↔core API version. Its MAJOR must equal `CORE_API_MAJOR` (currently `"1"`). |
| `supported: frozenset[Capability]` | attr | The capabilities this backend implements. Non-empty. |
| `connect(dsn, options) -> None` | async | Establish the connection/pool. Import the driver **lazily here** (see optional deps). |
| `health() -> bool` | async | Cheap liveness probe (e.g. `SELECT 1` / `ping`). Never raise — return `False`. |
| `close() -> None` | async | Release the pool/connection. Idempotent. |
| `execute(req) -> CapabilityResult` | async | Validate, translate, run, and map one request. Must call `validate_request` first. |
| `schema(resource, sample_size=None) -> dict` | async | Return `{"fields": {col: type, ...}}` for a resource. |
| `list_resources() -> list[str]` | async | List tables/collections available to the connection. |
| `validate_request(req) -> None` | sync | Raise `GuardValidationError` if the request is unsafe for this backend. |
| `cross_resource_refs(req) -> set[str]` | sync | Every *secondary* resource the request can reach (JOINs, `$lookup`, etc.). |

### CapabilityResult mapping

`CapabilityResult` has four fields: `rows`, `affected`, `scalar`, `meta`. Map each
capability to the right field so core (and the MCP tool layer) can interpret it.

| Capability | Result field(s) | Notes |
| --- | --- | --- |
| `READ`, `AGGREGATE` | `rows` | The matched documents/records. |
| `COUNT` | `scalar` | The integer count. Echo `rows` if convenient. |
| `WRITE_ONE`, `WRITE_MANY` | `affected` (+ `meta.lastrowid`) | Rows changed; for inserts, surface the new id in `meta` (e.g. MySQL `lastrowid`). Backends with `RETURNING` may also fill `rows`. |
| `DELETE_ONE`, `DELETE_MANY` | `affected` | Rows deleted. |
| `SCHEMA` | `rows` → `{"fields": {...}}` via `schema()` | Column/field → type map. |
| `INDEXES` | `rows` | One row per index. |
| `STATS`, `LIST_DATABASES`, `LIST_RESOURCES` | `rows` (or `meta`) | Introspection output. |
| `EXPLAIN` | `rows` or `meta` | The query plan. |
| `DDL_CREATE`, `DDL_DESTROY` | `affected`/`meta` | DDL outcome. Only declare in `supported` if you truly implement them. |

## Security requirements (critical)

These are non-negotiable. A plugin that violates them is a vulnerability in the
whole stack.

1. **Parameterize values, never interpolate.** User-supplied *values* (filter
   operands, document fields, update values) must travel as driver parameters
   (`$1`, `%s`, bind params) — never concatenated into the query string. See the
   Postgres translator: the dangerous string lives only in `args`, never in `sql`.
2. **Validate / allow-list identifiers.** Table/column/collection names that the
   backend treats as identifiers must be validated against a strict pattern (or an
   allow-list). The SQL plugins call `quote_ident()` which rejects anything that is
   not a plain identifier (`users; DROP TABLE x` → `GuardValidationError`).
3. **`validate_request` must reject injection and raw-SQL escape hatches.** Run it
   *before* translation/execution so a malicious request never reaches a
   connection. Reject any `options` key that smuggles raw SQL (`raw_sql`, `sql`,
   …). For document stores where the resource name is an arbitrary string (MongoDB
   collections), identifier validation may not apply — instead validate structure
   (banned aggregation stages, unsafe operators).
4. **`cross_resource_refs` must report every secondary resource.** When an
   operation can reach beyond its primary `resource` — a SQL `JOIN`, a MongoDB
   `$lookup`/`$graphLookup`/`$unionWith` — return the *names of every additional
   resource it touches*. This is how the cross-collection / cross-table guard
   works: core authorizes **each** returned name against policy independently. If
   you under-report here, you create a policy bypass. The MongoDB plugin extracts
   `$lookup` targets from the pipeline; the SQL plugins surface a structured
   `options["joins"]` list. Never silently allow a join to an unreported table.

## Registering your plugin

Plugins are discovered via the `guardmcp.plugins` entry-point group. In your
package's `pyproject.toml`:

```toml
[project.entry-points."guardmcp.plugins"]
mybackend = "my_pkg.plugin:MyBackendPlugin"
```

The registry (`PluginRegistry.discover()`) loads each entry point, checks the API
major version, and registers it under its `name`.

### Optional driver dependency pattern

Keep your DB driver an *optional* dependency so importing the plugin module never
forces the driver to be installed. Import it lazily inside `connect()`:

```toml
[project.optional-dependencies]
mybackend = ["my-driver>=1.0"]
```

```python
async def connect(self, dsn: str, options: dict) -> None:
    try:
        import my_driver  # lazy: only needed to actually connect
    except ImportError as exc:
        raise GuardExecutionError(
            "my-driver not installed; pip install guardmcp[mybackend]"
        ) from exc
    self._pool = await my_driver.create_pool(dsn, **(options or {}))
```

## Verifying your plugin

Use the shipped conformance kit. It runs **static** checks (no live DB, no
`connect()`):

```python
from guardmcp.conformance import assert_plugin_conformant
from my_pkg.plugin import MyBackendPlugin


def test_mybackend_conformance():
    assert_plugin_conformant(MyBackendPlugin())


def test_mybackend_rejects_injection():
    # SQL-style backends: opt into identifier-injection rejection.
    assert_plugin_conformant(
        MyBackendPlugin(), expects_identifier_validation=True
    )
```

`check_plugin_conformance(plugin) -> list[str]` returns failure strings (empty ==
conformant) if you prefer to inspect them; `assert_plugin_conformant` raises
`AssertionError` with the joined failures. Pass
`expects_identifier_validation=True` for SQL-style backends so the kit also asserts
that an injection identifier (`"x; DROP TABLE y"`) raises `GuardValidationError`.
Leave it `False` for document stores with arbitrary resource names.

## Worked examples

Read the three builtins as references:

- `src/guardmcp/plugins/postgres/plugin.py` + `translate.py` + `validate.py` —
  relational, `RETURNING`, parameterized SQL, identifier validation.
- `src/guardmcp/plugins/mysql/plugin.py` — same shape with dialect deltas
  (`%s` placeholders, no `RETURNING`; `affected` + `meta.lastrowid`).
- `src/guardmcp/plugins/mongodb/plugin.py` + `guard.py` — document store;
  structural validation and `$lookup` cross-resource extraction.

## Stability & Versioning

GuardMCP treats the plugin surface as a versioned **public contract** under
[semantic versioning](https://semver.org/). Author against the public symbols
and your plugin keeps working across core minor/patch releases.

### Public contract (semver-stable)

These are the only symbols a plugin should depend on. Breaking changes to them
bump the **core major version**:

- `DatabasePlugin` (`core/interfaces/plugin.py`) — the ABC you implement.
- `Capability`, `CapabilityRequest`, `CapabilityResult`
  (`core/interfaces/capability.py`) — the request/result value objects.
- The `GuardValidationError` / `GuardError` taxonomy
  (`core/interfaces/errors.py`) that `validate_request` raises.

### `api_version` and `CORE_API_MAJOR`

Every plugin declares `api_version` (e.g. `"1.0"`). At registration the core
checks that its **major** matches `CORE_API_MAJOR`
(`core/registry/registry.py`); a mismatch raises `PluginVersionError` and the
plugin is refused. The major is what semver guarantees:

- Same major (`"1.x"` against `CORE_API_MAJOR == "1"`) → the public contract is
  source-compatible; your plugin loads unchanged.
- A breaking change to any public symbol bumps `CORE_API_MAJOR` to `"2"`; plugins
  must declare `api_version = "2.x"` to load.

### Deprecation policy

When a public symbol must change, the old surface is kept for **at least one
minor release** alongside the new one, with a documented `DeprecationWarning`.
Only after that grace minor is the old surface removed (which, if it is a
breaking removal, rides a major bump). Watch the release notes and resolve
deprecation warnings before the next major.

### Internal — may change without notice

These are **not** part of the contract. Do not import or subclass them in a
plugin; they can change in any release:

- `core/interfaces/backend.py` (the Mongo-shaped `Backend`) and
  `CapabilityExecutorAdapter` — the internal bridge the core uses to drive your
  plugin. Plugins implement `DatabasePlugin`, never `Backend`.
- Anything under `core/` not listed under *Public contract* above
  (pipeline, policy engine, audit logger, masking, observability internals).

### Public vs internal at a glance

| Symbol / module                                   | Status   | Stability                         |
|---------------------------------------------------|----------|-----------------------------------|
| `DatabasePlugin`                                  | Public   | semver; major-gated by `api_version` |
| `Capability` / `CapabilityRequest` / `CapabilityResult` | Public   | semver                            |
| `GuardError` / `GuardValidationError` taxonomy    | Public   | semver                            |
| `CORE_API_MAJOR` (compatibility constant)         | Public   | bumped only on a breaking major   |
| `Backend` (`core/interfaces/backend.py`)          | Internal | may change without notice         |
| `CapabilityExecutorAdapter`                       | Internal | may change without notice         |
| `GuardPipeline`, `PolicyEngine`, `AuditLogger`, masking, observability | Internal | may change without notice         |
