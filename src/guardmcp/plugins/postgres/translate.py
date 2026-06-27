"""
PURE translation: CapabilityRequest -> (sql, args) for PostgreSQL.

This is now a THIN dialect over the shared :mod:`guardmcp.plugins.sql` core. It
performs NO database calls and remains the security-critical heart of the
PostgreSQL plugin. Two invariants (enforced in the shared core) make the output
injection-safe BY CONSTRUCTION:

1. Identifiers are validated against ``^[A-Za-z_][A-Za-z0-9_]*$`` (per dot part,
   at most schema.table) before being placed into SQL text; invalid identifiers
   raise GuardValidationError.
2. Values are NEVER string-formatted into SQL — they are emitted as asyncpg
   positional placeholders ($1, $2, ...) and collected into an ``args`` list.

PostgreSQL dialect specifics: ``$n`` placeholders, bare (unquoted but validated)
identifiers, ``$in`` -> ``= ANY(array)``, INSERT/UPDATE ``RETURNING *``,
single-row DELETE via a ctid subquery, and pg_* / information_schema catalogs.
"""

from __future__ import annotations

from ...core.interfaces.capability import CapabilityRequest
from ..sql.translate_base import (
    _OPERATORS,
    Dialect,
    SqlTranslator,
    Translated,
    _ArgCounter,
    validate_ident,
)

__all__ = ["Translated", "quote_ident", "translate", "_OPERATORS"]


def quote_ident(name: str) -> str:
    """Validate a (possibly schema-qualified) identifier and return it verbatim.

    Each dot-separated part must match ``^[A-Za-z_][A-Za-z0-9_]*$``. We do NOT
    double-quote: validation guarantees the identifier contains only safe chars,
    so plain text is injection-free. An invalid identifier raises
    GuardValidationError — we never interpolate an unvalidated name.
    """
    validate_ident(name)
    return name


def _schema_from_options(req: CapabilityRequest) -> str | None:
    schema = req.options.get("schema")
    if schema is None:
        return None
    quote_ident(schema)  # validate
    return schema


def _schema_sql(req: CapabilityRequest, counter: _ArgCounter) -> str:
    table_ph = counter.add(req.resource)
    sql = (
        "SELECT column_name, data_type FROM information_schema.columns "
        f"WHERE table_name = {table_ph}"
    )
    schema = _schema_from_options(req)
    if schema is not None:
        sql += f" AND table_schema = {counter.add(schema)}"
    sql += " ORDER BY ordinal_position"
    return sql


def _indexes_sql(req: CapabilityRequest, counter: _ArgCounter) -> str:
    return (
        f"SELECT indexname, indexdef FROM pg_indexes WHERE tablename = {counter.add(req.resource)}"
    )


def _list_resources_sql(req: CapabilityRequest, counter: _ArgCounter) -> str:
    schema = _schema_from_options(req) or "public"
    return (
        "SELECT table_name FROM information_schema.tables "
        f"WHERE table_schema = {counter.add(schema)}"
    )


def _list_databases_sql(req: CapabilityRequest, counter: _ArgCounter) -> str:
    return "SELECT datname FROM pg_database WHERE datistemplate = false"


def _stats_sql(req: CapabilityRequest, counter: _ArgCounter) -> str:
    return (
        "SELECT current_database() AS database, pg_database_size(current_database()) AS size_bytes"
    )


_DIALECT = Dialect(
    name="PostgresPlugin",
    placeholder=lambda n: f"${n}",
    quote_ident=quote_ident,
    supports_returning=True,
    in_uses_array=True,
    delete_one_strategy="ctid",
    schema_sql=_schema_sql,
    indexes_sql=_indexes_sql,
    list_resources_sql=_list_resources_sql,
    list_databases_sql=_list_databases_sql,
    stats_sql=_stats_sql,
)

_TRANSLATOR = SqlTranslator(_DIALECT)


def translate(req: CapabilityRequest) -> Translated:
    """Translate a CapabilityRequest into parameterized SQL + positional args.

    Raises GuardValidationError for unsupported capabilities (AGGREGATE, DDL) and
    for any unsafe construct. DDL is intentionally refused for now — see plugin.
    """
    return _TRANSLATOR.translate(req)
