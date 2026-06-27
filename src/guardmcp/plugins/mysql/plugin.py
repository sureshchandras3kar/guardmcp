"""
Formal MySQL DatabasePlugin.

Mirrors the PostgreSQL plugin with MySQL dialect deltas. Translation
(translate.py) is pure and injection-safe by construction; execution runs the
parameterized SQL against an aiomysql pool using ``%s`` placeholders.

aiomysql is an OPTIONAL dependency. Importing THIS module must never require it —
the import is performed lazily inside connect(). Install with
``pip install guardmcp[mysql]``.

Dialect note: MySQL has no RETURNING. Writes/deletes therefore report the
affected row count (cursor.rowcount) and, for inserts, the auto-increment id
(cursor.lastrowid) in CapabilityResult.meta — NOT the inserted/updated rows.
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
from ..sql.cost import normalize_mysql_explain
from . import translate as _t
from . import validate as _v

# Capabilities whose results are row sets returned via cursor.fetchall().
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


class MySQLPlugin(DatabasePlugin):
    name = "mysql"
    api_version = "1.0"
    # #7: static dialect features — readable from the class manifest WITHOUT
    # instantiating the plugin or importing aiomysql.
    dialect_features = {
        "placeholder_style": "format",  # %s
        "supports_returning": False,
        "identifier_quote": "`",
        "supports_cost_estimate": True,  # via EXPLAIN FORMAT=JSON, no execution
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
        # LAZY import: keeps aiomysql an optional dependency. Importing this
        # module never touches aiomysql; only an actual connect() does.
        try:
            import aiomysql
        except ImportError as exc:  # pragma: no cover - exercised without aiomysql
            raise GuardExecutionError(
                "aiomysql not installed; pip install guardmcp[mysql]"
            ) from exc
        pool_opts = dict(options or {})
        # aiomysql.create_pool takes discrete connection kwargs (host, port,
        # user, password, db). Allow either a structured options dict or a
        # dsn:// passed through under options.
        if dsn and "dsn" not in pool_opts and "host" not in pool_opts:
            pool_opts.setdefault("dsn", dsn)
        try:
            self._pool = await aiomysql.create_pool(**pool_opts)
        except Exception as exc:
            raise GuardExecutionError(f"failed to create connection pool: {exc}") from exc

    async def health(self) -> bool:
        if self._pool is None:
            return False
        try:
            async with self._pool.acquire() as conn, conn.cursor() as cur:
                await cur.execute("SELECT 1")
                await cur.fetchall()
            return True
        except Exception:
            return False

    async def close(self) -> None:
        if self._pool is not None:
            close = self._pool.close()
            if close is not None:  # aiomysql pool.close() may be a coroutine
                await close

    # ── Execution ─────────────────────────────────────────────────────────────
    async def execute(self, req: CapabilityRequest) -> CapabilityResult:
        # Validate BEFORE touching the pool — injection attempts never reach a
        # connection.
        self.validate_request(req)
        translated = _t.translate(req)
        if self._pool is None:
            raise GuardExecutionError("MySQLPlugin has no pool bound")
        try:
            async with self._pool.acquire() as conn, conn.cursor() as cur:
                await cur.execute(translated.sql, translated.args)
                if req.capability in _FETCH_CAPS:
                    rows = await cur.fetchall()
                    mapped = self._map_rows(cur, rows)
                    return self._rows_result(req, mapped)
                # writes / deletes — MySQL has no RETURNING. Report affected
                # rows and (for inserts) the auto-increment lastrowid.
                affected = cur.rowcount
                meta: dict[str, Any] = {}
                lastrowid = getattr(cur, "lastrowid", None)
                if lastrowid:
                    meta["lastrowid"] = lastrowid
                return CapabilityResult(
                    rows=[],
                    affected=affected if affected is not None and affected >= 0 else None,
                    meta=meta,
                )
        except (GuardValidationError, GuardExecutionError):
            raise
        except Exception as exc:
            raise GuardExecutionError(f"mysql execution failed: {exc}") from exc

    def _rows_result(
        self, req: CapabilityRequest, mapped: list[dict[str, Any]]
    ) -> CapabilityResult:
        if req.capability == Capability.COUNT:
            scalar = 0
            if mapped:
                first = mapped[0]
                # count(*) comes back under "count(*)"; fall back to first value.
                scalar = first.get("count(*)", next(iter(first.values()), 0))
            return CapabilityResult(rows=mapped, scalar=int(scalar))
        return CapabilityResult(rows=mapped)

    @staticmethod
    def _map_rows(cur: Any, rows: Any) -> list[dict[str, Any]]:
        """Map cursor rows to dicts.

        aiomysql's default cursor returns tuples; we map them via
        cursor.description. A DictCursor (or fake rows) already yields dicts.
        """
        mapped: list[dict[str, Any]] = []
        description = getattr(cur, "description", None)
        for row in rows:
            if isinstance(row, dict):
                mapped.append(dict(row))
            elif description is not None:
                cols = [d[0] for d in description]
                mapped.append(dict(zip(cols, row, strict=False)))
            else:
                mapped.append({"value": row})
        return mapped

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
        """Estimate a READ/COUNT via ``EXPLAIN FORMAT=JSON <sql>`` (plan only —
        no execution), normalized to a CostEstimate. NEVER returns the raw plan.
        Best-effort: failures degrade to UNKNOWN + warning."""
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
            sql = f"EXPLAIN FORMAT=JSON {translated.sql}"
            async with self._pool.acquire() as conn, conn.cursor() as cur:
                await cur.execute(sql, translated.args)
                rows = await cur.fetchall()
            payload = self._extract_explain_json(cur, rows)
        except Exception as exc:
            return CostEstimate(
                estimated_cost=CostLevel.UNKNOWN,
                warnings=[f"explain failed: {type(exc).__name__}"],
            )
        return normalize_mysql_explain(payload)

    @staticmethod
    def _extract_explain_json(cur: Any, rows: Any) -> Any:
        """EXPLAIN FORMAT=JSON returns one row with the JSON plan in its single
        column (named EXPLAIN). May be a JSON string or an already-parsed dict."""
        if not rows:
            return None
        first = rows[0]
        value: Any
        if isinstance(first, dict):
            value = first.get("EXPLAIN", next(iter(first.values()), None))
        elif isinstance(first, (list, tuple)):
            value = first[0] if first else None
        else:
            value = first
        if isinstance(value, (bytes, bytearray)):
            value = value.decode("utf-8")
        if isinstance(value, str):
            return _json.loads(value)
        return value
