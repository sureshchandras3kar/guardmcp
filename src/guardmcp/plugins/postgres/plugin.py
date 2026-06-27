"""
Formal PostgreSQL DatabasePlugin.

Proves the GuardMCP plugin abstraction generalizes to a relational paradigm.
Translation (translate.py) is pure and injection-safe by construction; execution
runs the parameterized SQL against an asyncpg pool.

asyncpg is an OPTIONAL dependency. Importing THIS module must never require it —
the import is performed lazily inside connect(). Install with
``pip install guardmcp[postgres]``.
"""

from __future__ import annotations

import json as _json
from typing import Any

from ...core.interfaces.capability import (
    Capability,
    CapabilityRequest,
    CapabilityResult,
)
from ...core.interfaces.cost import CostEstimate, CostLevel
from ...core.interfaces.errors import GuardExecutionError, GuardValidationError
from ...core.interfaces.plugin import DatabasePlugin
from ..sql.cost import normalize_postgres_explain
from . import translate as _t
from . import validate as _v


def _affected_from_status(status: Any) -> int:
    """Parse asyncpg command status tag → affected row count.

    'DELETE 5' → 5, 'UPDATE 3' → 3, 'INSERT 0 1' → 1 (last integer).
    """
    if not isinstance(status, str):
        return 0
    parts = status.split()
    for tok in reversed(parts):
        if tok.isdigit():
            return int(tok)
    return 0


# Capabilities reading-style results are returned via fetch(); writes/deletes use
# RETURNING (also fetch) or execute() for affected-row status.
_FETCH_CAPS: frozenset[Capability] = frozenset(
    {
        Capability.READ,
        Capability.COUNT,
        Capability.SCHEMA,
        Capability.INDEXES,
        Capability.LIST_RESOURCES,
        Capability.LIST_DATABASES,
        Capability.STATS,
        Capability.EXPLAIN,
    }
)


class PostgresPlugin(DatabasePlugin):
    name = "postgres"
    api_version = "1.0"
    # #7: static dialect features — readable from the class manifest WITHOUT
    # instantiating the plugin or importing asyncpg.
    dialect_features = {
        "placeholder_style": "numeric",  # $1, $2, ...
        "supports_returning": True,
        "identifier_quote": '"',
        "supports_cost_estimate": True,  # via EXPLAIN (FORMAT JSON), no execution
    }
    supported: frozenset[Capability] = frozenset(
        {
            Capability.READ,
            Capability.COUNT,
            Capability.WRITE_ONE,
            Capability.WRITE_MANY,
            Capability.DELETE_ONE,
            Capability.DELETE_MANY,
            Capability.SCHEMA,
            Capability.INDEXES,
            Capability.LIST_RESOURCES,
            Capability.LIST_DATABASES,
            Capability.STATS,
            Capability.EXPLAIN,
            Capability.ESTIMATE,
        }
    )

    def __init__(self, pool: Any | None = None) -> None:
        # Tests inject a fake pool; production builds one via connect().
        self._pool = pool

    # ── Lifecycle ───────────────────────────────────────────────────────────
    async def connect(self, dsn: str, options: dict) -> None:
        # LAZY import: keeps asyncpg an optional dependency. Importing this
        # module never touches asyncpg; only an actual connect() does.
        try:
            import asyncpg
        except ImportError as exc:  # pragma: no cover - exercised without asyncpg
            raise GuardExecutionError(
                "asyncpg not installed; pip install guardmcp[postgres]"
            ) from exc
        pool_opts = dict(options or {})
        try:
            self._pool = await asyncpg.create_pool(dsn, **pool_opts)
        except Exception as exc:
            raise GuardExecutionError(f"failed to create connection pool: {exc}") from exc

    async def health(self) -> bool:
        if self._pool is None:
            return False
        try:
            async with self._pool.acquire() as conn:
                await conn.fetch("SELECT 1")
            return True
        except Exception:
            return False

    async def close(self) -> None:
        if self._pool is not None:
            close = self._pool.close()
            if close is not None:  # asyncpg pool.close() is a coroutine
                await close

    # ── Execution ─────────────────────────────────────────────────────────────
    async def execute(self, req: CapabilityRequest) -> CapabilityResult:
        # Validate BEFORE touching the pool — injection attempts never reach a
        # connection.
        self.validate_request(req)
        translated = _t.translate(req)
        if self._pool is None:
            raise GuardExecutionError("PostgresPlugin has no pool bound")
        try:
            async with self._pool.acquire() as conn:
                if req.capability in _FETCH_CAPS:
                    rows = await conn.fetch(translated.sql, *translated.args)
                    return self._rows_result(req, rows)
                # writes / deletes. With RETURNING the affected rows come back via
                # fetch(); WITHOUT it (e.g. plain DELETE/UPDATE) fetch() yields []
                # and the true count lives in asyncpg's status tag ("DELETE 5"),
                # so use execute() + parse the tag. Otherwise affected is wrong (0).
                if "RETURNING" in translated.sql.upper():
                    rows = await conn.fetch(translated.sql, *translated.args)
                    mapped = [self._row_to_dict(r) for r in rows]
                    return CapabilityResult(rows=mapped, affected=len(mapped))
                status = await conn.execute(translated.sql, *translated.args)
                return CapabilityResult(rows=[], affected=_affected_from_status(status))
        except (GuardValidationError, GuardExecutionError):
            raise
        except Exception as exc:
            raise GuardExecutionError(f"postgres execution failed: {exc}") from exc

    def _rows_result(self, req: CapabilityRequest, rows: Any) -> CapabilityResult:
        mapped = [self._row_to_dict(r) for r in rows]
        if req.capability == Capability.COUNT:
            scalar = 0
            if mapped:
                # count(*) comes back under "count"; fall back to first value.
                first = mapped[0]
                scalar = first.get("count", next(iter(first.values()), 0))
            return CapabilityResult(rows=mapped, scalar=int(scalar))
        return CapabilityResult(rows=mapped)

    @staticmethod
    def _row_to_dict(row: Any) -> dict[str, Any]:
        # asyncpg Records support dict(record); fake rows may already be dicts.
        if isinstance(row, dict):
            return dict(row)
        try:
            return dict(row)
        except (TypeError, ValueError):
            return {"value": row}

    # ── Introspection ───────────────────────────────────────────────────────
    async def schema(self, resource: str, sample_size: int | None = None) -> dict:
        req = CapabilityRequest(capability=Capability.SCHEMA, resource=resource)
        result = await self.execute(req)
        fields: dict[str, Any] = {}
        for row in result.rows:
            col = row.get("column_name")
            if col is not None:
                fields[col] = row.get("data_type")
        return {"fields": fields}

    async def list_resources(self) -> list[str]:
        req = CapabilityRequest(capability=Capability.LIST_RESOURCES)
        result = await self.execute(req)
        return [row["table_name"] for row in result.rows if "table_name" in row]

    # ── Validation / guard ownership ─────────────────────────────────────────
    def validate_request(self, req: CapabilityRequest) -> None:
        _v.validate_request(req)

    def cross_resource_refs(self, req: CapabilityRequest) -> set[str]:
        return _v.cross_resource_refs(req)

    # ── Cost estimation ──────────────────────────────────────────────────────
    async def estimate(self, req: CapabilityRequest) -> CostEstimate:
        """Estimate a READ/COUNT via ``EXPLAIN (FORMAT JSON) <sql>`` (plan only —
        NO ANALYZE, no execution), normalized to a CostEstimate. NEVER returns
        the raw plan. Best-effort: failures degrade to UNKNOWN + warning."""
        if req.capability not in (Capability.READ, Capability.COUNT):
            return CostEstimate(
                estimated_cost=CostLevel.UNKNOWN,
                warnings=[f"estimation not supported for {req.capability.value}"],
            )
        if self._pool is None:
            return CostEstimate(
                estimated_cost=CostLevel.UNKNOWN, warnings=["no pool bound for estimation"]
            )
        try:
            self.validate_request(req)
            translated = _t.translate(req)
            sql = f"EXPLAIN (FORMAT JSON) {translated.sql}"
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(sql, *translated.args)
            payload = self._extract_explain_json(rows)
        except Exception as exc:
            return CostEstimate(
                estimated_cost=CostLevel.UNKNOWN,
                warnings=[f"explain failed: {type(exc).__name__}"],
            )
        return normalize_postgres_explain(payload)

    @staticmethod
    def _extract_explain_json(rows: Any) -> Any:
        """EXPLAIN (FORMAT JSON) returns a single row whose one column holds the
        JSON plan (a string or already-parsed list, depending on the driver)."""
        if not rows:
            return None
        first = rows[0]
        value = (
            dict(first).get("QUERY PLAN")
            if isinstance(first, dict) or hasattr(first, "keys")
            else first
        )
        if value is None:
            # Fall back to the first column value.
            try:
                value = next(iter(dict(first).values()))
            except Exception:
                value = first
        if isinstance(value, str):
            return _json.loads(value)
        return value
