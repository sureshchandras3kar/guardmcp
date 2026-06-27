"""
Dialect-parameterized, PURE translation: CapabilityRequest -> (sql, args).

This module performs NO database calls. It is the security-critical heart shared
by the relational plugins. Two invariants make the output injection-safe BY
CONSTRUCTION:

1. Identifiers (table / column / schema names) are validated against a strict
   regex before they are ever placed into SQL text. An invalid identifier raises
   GuardValidationError; nothing is interpolated otherwise. The dialect decides
   how (or whether) a validated identifier is quoted.
2. Values are NEVER string-formatted into SQL. They are always emitted as the
   dialect's placeholders and collected into a positional ``args`` list.

If a translation cannot be expressed safely, we raise GuardValidationError rather
than emit unsafe SQL.

A :class:`Dialect` captures every observed delta between backends:
  - placeholder style ($1 vs %s),
  - identifier quoting (bare vs backtick),
  - ``$in`` expansion (ANY(array) vs N placeholders),
  - INSERT RETURNING support,
  - single-row DELETE strategy (ctid subquery vs LIMIT 1),
  - catalog/introspection queries (schema, indexes, list, databases, stats),
  - the backend name used in "not supported" error messages.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ...core.interfaces.capability import Capability, CapabilityRequest
from ...core.interfaces.errors import GuardValidationError

# A single SQL identifier part: letter/underscore start, then word chars.
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Bounded operator set for filter dicts. Maps the operator key to the SQL
# comparison operator. $in is handled specially per dialect.
_OPERATORS: dict[str, str] = {
    "$gt": ">",
    "$gte": ">=",
    "$lt": "<",
    "$lte": "<=",
    "$ne": "!=",
}


@dataclass
class Translated:
    """Result of a pure translation: parameterized SQL plus positional args."""

    sql: str
    args: list[Any] = field(default_factory=list)

    def __iter__(self):
        # Allow tuple-unpacking: sql, args = translate(req)
        yield self.sql
        yield self.args


# ── identifier validation ──────────────────────────────────────────────────────


def validate_ident(name: str) -> list[str]:
    """Validate a (possibly schema-qualified) identifier; return its parts.

    Each dot-separated part must match ``^[A-Za-z_][A-Za-z0-9_]*$`` and at most
    ``schema.table`` is allowed. Raises GuardValidationError on any violation. The
    caller (a dialect) decides how to quote the validated parts.
    """
    if not isinstance(name, str) or not name:
        raise GuardValidationError(f"invalid identifier: {name!r}")
    parts = name.split(".")
    if len(parts) > 2:
        raise GuardValidationError(f"invalid identifier {name!r}: at most schema.table is allowed")
    for part in parts:
        if not _IDENT_RE.match(part):
            raise GuardValidationError(f"invalid identifier part: {part!r}")
    return parts


# ── dialect ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Dialect:
    """Captures the per-backend deltas the shared translator needs.

    ``name`` is used in "not supported" error messages. ``quote_ident`` validates
    and quotes an identifier. The catalog-SQL callables receive the validated
    request and a fresh :class:`_ArgCounter` and return the SQL string (appending
    any bound values to the counter), so they can parameterize freely.
    """

    name: str
    # placeholder(n) where n is the 1-based position of the value just added.
    placeholder: Callable[[int], str]
    quote_ident: Callable[[str], str]
    supports_returning: bool
    # $in: True -> single placeholder bound to the whole list (ANY(array));
    #      False -> one placeholder per element (IN (...)).
    in_uses_array: bool
    # Single-row DELETE strategy: "ctid" subquery or "limit" (LIMIT 1).
    delete_one_strategy: str
    # Catalog/introspection SQL builders (sql str; may append to counter.args).
    schema_sql: Callable[[CapabilityRequest, _ArgCounter], str]
    indexes_sql: Callable[[CapabilityRequest, _ArgCounter], str]
    list_resources_sql: Callable[[CapabilityRequest, _ArgCounter], str]
    list_databases_sql: Callable[[CapabilityRequest, _ArgCounter], str]
    stats_sql: Callable[[CapabilityRequest, _ArgCounter], str]


# ── arg counter ────────────────────────────────────────────────────────────────


class _ArgCounter:
    """Issues placeholders (dialect-specific) and accumulates the bound values."""

    def __init__(self, placeholder: Callable[[int], str]) -> None:
        self.args: list[Any] = []
        self._placeholder = placeholder

    def add(self, value: Any) -> str:
        self.args.append(value)
        return self._placeholder(len(self.args))


# ── translator ─────────────────────────────────────────────────────────────────


class SqlTranslator:
    """Dialect-parameterized translator. ``translate(req)`` -> Translated."""

    def __init__(self, dialect: Dialect) -> None:
        self.d = dialect

    # -- helpers ------------------------------------------------------------------

    def _counter(self) -> _ArgCounter:
        return _ArgCounter(self.d.placeholder)

    def _quote(self, name: str) -> str:
        return self.d.quote_ident(name)

    def _build_where(self, filter_: dict[str, Any] | None, counter: _ArgCounter) -> str:
        """Build a parameterized WHERE clause (without the WHERE keyword).

        Returns "" when there is no filter. Each value is parameterized; only the
        validated column identifier is placed into SQL text. Multiple keys are
        AND-combined.
        """
        if not filter_:
            return ""
        clauses: list[str] = []
        for col, cond in filter_.items():
            ident = self._quote(col)
            if isinstance(cond, dict):
                for op, val in cond.items():
                    if op == "$in":
                        clauses.append(self._build_in(ident, val, counter))
                    elif op in _OPERATORS:
                        ph = counter.add(val)
                        clauses.append(f"{ident} {_OPERATORS[op]} {ph}")
                    else:
                        raise GuardValidationError(f"unsupported operator: {op!r}")
            else:
                ph = counter.add(cond)
                clauses.append(f"{ident} = {ph}")
        return " AND ".join(clauses)

    def _build_in(self, ident: str, val: Any, counter: _ArgCounter) -> str:
        if not isinstance(val, (list, tuple)):
            raise GuardValidationError("$in expects a list")
        if self.d.in_uses_array:
            ph = counter.add(list(val))
            return f"{ident} = ANY({ph})"
        # Expanded placeholders: one per element.
        if not val:
            raise GuardValidationError("$in expects a non-empty list")
        placeholders = [counter.add(v) for v in val]
        return f"{ident} IN ({', '.join(placeholders)})"

    def _projection_columns(self, projection: dict[str, Any] | None) -> str:
        if not projection:
            return "*"
        cols = [self._quote(c) for c in projection]
        return ", ".join(cols)

    # -- per-capability translators ----------------------------------------------

    def _translate_read(self, req: CapabilityRequest, explain: bool = False) -> Translated:
        table = self._quote(req.resource)
        cols = self._projection_columns(req.projection)
        counter = self._counter()
        where = self._build_where(req.filter, counter)
        sql = f"SELECT {cols} FROM {table}"
        if where:
            sql += f" WHERE {where}"
        if req.limit is not None:
            sql += f" LIMIT {counter.add(req.limit)}"
        if req.skip is not None:
            sql += f" OFFSET {counter.add(req.skip)}"
        if explain:
            sql = "EXPLAIN " + sql
        return Translated(sql, counter.args)

    def _translate_count(self, req: CapabilityRequest) -> Translated:
        table = self._quote(req.resource)
        counter = self._counter()
        where = self._build_where(req.filter, counter)
        sql = f"SELECT count(*) FROM {table}"
        if where:
            sql += f" WHERE {where}"
        return Translated(sql, counter.args)

    def _translate_insert(self, req: CapabilityRequest) -> Translated:
        """Single-row insert from documents[0], or UPDATE if filter+update present."""
        if req.update is not None and req.filter is not None and not req.documents:
            return self._translate_update(req)
        if not req.documents:
            raise GuardValidationError("WRITE_ONE requires documents or filter+update")
        return self._translate_insert_rows(req, [req.documents[0]])

    def _translate_insert_many(self, req: CapabilityRequest) -> Translated:
        if not req.documents:
            raise GuardValidationError("WRITE_MANY requires documents")
        return self._translate_insert_rows(req, req.documents)

    def _translate_insert_rows(
        self, req: CapabilityRequest, docs: list[dict[str, Any]]
    ) -> Translated:
        table = self._quote(req.resource)
        # Use the column order of the first document; all rows must share it.
        columns = list(docs[0].keys())
        if not columns:
            raise GuardValidationError("cannot insert an empty document")
        quoted_cols = [self._quote(c) for c in columns]
        counter = self._counter()
        row_clauses: list[str] = []
        for doc in docs:
            placeholders = [counter.add(doc.get(c)) for c in columns]
            row_clauses.append("(" + ", ".join(placeholders) + ")")
        sql = f"INSERT INTO {table} ({', '.join(quoted_cols)}) VALUES {', '.join(row_clauses)}"
        if self.d.supports_returning:
            sql += " RETURNING *"
        return Translated(sql, counter.args)

    def _translate_update(self, req: CapabilityRequest) -> Translated:
        table = self._quote(req.resource)
        if not req.update:
            raise GuardValidationError("UPDATE requires an update document")
        # Support a Mongo-style {"$set": {...}} as well as a flat dict.
        set_doc = req.update.get("$set") if "$set" in req.update else req.update
        if not isinstance(set_doc, dict) or not set_doc:
            raise GuardValidationError("UPDATE set clause must be a non-empty object")
        counter = self._counter()
        set_clauses: list[str] = []
        for col, val in set_doc.items():
            ident = self._quote(col)
            set_clauses.append(f"{ident} = {counter.add(val)}")
        where = self._build_where(req.filter, counter)
        sql = f"UPDATE {table} SET {', '.join(set_clauses)}"
        if where:
            sql += f" WHERE {where}"
        if self.d.supports_returning:
            sql += " RETURNING *"
        return Translated(sql, counter.args)

    def _translate_delete(self, req: CapabilityRequest, single: bool) -> Translated:
        table = self._quote(req.resource)
        counter = self._counter()
        where = self._build_where(req.filter, counter)
        if single and not where:
            # DELETE_ONE with no filter is too broad to be a single-row delete.
            raise GuardValidationError("DELETE_ONE requires a filter")
        sql = f"DELETE FROM {table}"
        if where:
            sql += f" WHERE {where}"
        if single:
            sql = self._delete_one_sql(table, where, counter)
        return Translated(sql, counter.args)

    def _delete_one_sql(self, table: str, where: str, counter: _ArgCounter) -> str:
        """Bound a single-row DELETE per the dialect strategy."""
        if self.d.delete_one_strategy == "ctid":
            # No native single-row DELETE: bound via a ctid subquery so DELETE_ONE
            # never removes more than one row, mirroring MongoDB delete_one.
            inner = f"SELECT ctid FROM {table}"
            if where:
                inner += f" WHERE {where}"
            inner += " LIMIT 1"
            return f"DELETE FROM {table} WHERE ctid IN ({inner})"
        if self.d.delete_one_strategy == "limit":
            # Dialect supports LIMIT on DELETE — bounds DELETE_ONE to one row.
            sql = f"DELETE FROM {table}"
            if where:
                sql += f" WHERE {where}"
            sql += " LIMIT 1"
            return sql
        raise GuardValidationError(f"unknown delete_one strategy: {self.d.delete_one_strategy!r}")

    # -- public dispatch ----------------------------------------------------------

    def translate(self, req: CapabilityRequest) -> Translated:
        """Translate a CapabilityRequest into parameterized SQL + positional args.

        Raises GuardValidationError for unsupported capabilities (AGGREGATE, DDL)
        and for any unsafe construct. DDL is intentionally refused for now.
        """
        cap = req.capability
        if cap == Capability.READ:
            return self._translate_read(req)
        if cap == Capability.EXPLAIN:
            return self._translate_read(req, explain=True)
        if cap == Capability.COUNT:
            return self._translate_count(req)
        if cap == Capability.WRITE_ONE:
            return self._translate_insert(req)
        if cap == Capability.WRITE_MANY:
            return self._translate_insert_many(req)
        if cap == Capability.DELETE_ONE:
            return self._translate_delete(req, single=True)
        if cap == Capability.DELETE_MANY:
            return self._translate_delete(req, single=False)
        if cap == Capability.SCHEMA:
            return self._catalog(self.d.schema_sql, req)
        if cap == Capability.INDEXES:
            return self._catalog(self.d.indexes_sql, req)
        if cap == Capability.LIST_RESOURCES:
            return self._catalog(self.d.list_resources_sql, req)
        if cap == Capability.LIST_DATABASES:
            return self._catalog(self.d.list_databases_sql, req)
        if cap == Capability.STATS:
            return self._catalog(self.d.stats_sql, req)
        if cap in (Capability.DDL_CREATE, Capability.DDL_DESTROY):
            raise GuardValidationError(f"DDL not supported via {self.d.name} yet")
        if cap == Capability.AGGREGATE:
            raise GuardValidationError(f"AGGREGATE not supported via {self.d.name}")
        raise GuardValidationError(f"unsupported capability: {cap!r}")

    def _catalog(
        self,
        builder: Callable[[CapabilityRequest, _ArgCounter], str],
        req: CapabilityRequest,
    ) -> Translated:
        counter = self._counter()
        sql = builder(req, counter)
        return Translated(sql, counter.args)
