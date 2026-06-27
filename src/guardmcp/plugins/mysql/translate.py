"""
PURE translation: CapabilityRequest -> (sql, args) for MySQL.

This is now a THIN dialect over the shared :mod:`guardmcp.plugins.sql` core. It
performs NO database calls and remains the security-critical heart of the MySQL
plugin. Two invariants (enforced in the shared core) make the output
injection-safe BY CONSTRUCTION:

1. Identifiers are validated against ``^[A-Za-z_][A-Za-z0-9_]*$`` (per dot part,
   at most schema.table) before being placed into SQL text; invalid identifiers
   raise GuardValidationError. Validated identifiers are backtick-quoted (MySQL
   dialect): ``table`` -> ```table```, ``db.table`` -> ```db`.`table```.
2. Values are NEVER string-formatted into SQL — they are emitted as MySQL ``%s``
   placeholders (aiomysql / PyMySQL paramstyle) and collected into an ``args``
   list — a positional list, same shape as the PostgreSQL plugin.

Dialect deltas vs PostgreSQL:
- Placeholders are ``%s`` (not ``$1``).
- Identifiers are backtick-quoted.
- ``$in`` expands to N ``%s`` placeholders (MySQL has no ANY(array)).
- INSERT/UPDATE have NO RETURNING — the plugin reports affected/lastrowid.
- DELETE_ONE uses ``LIMIT 1`` (MySQL supports it; cleaner than PG ctid).
- Introspection uses information_schema + DATABASE(), SHOW INDEX, SHOW DATABASES.
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
    """Validate a (possibly schema-qualified) identifier and backtick-quote it.

    Each dot-separated part must match ``^[A-Za-z_][A-Za-z0-9_]*$``. Validation
    guarantees each part contains only safe chars; we then wrap each part in
    backticks (MySQL dialect): ``db.table`` -> ```db`.`table```. An invalid
    identifier raises GuardValidationError — we never interpolate an unvalidated
    name.
    """
    parts = validate_ident(name)
    return ".".join(f"`{part}`" for part in parts)


def _schema_sql(req: CapabilityRequest, counter: _ArgCounter) -> str:
    table_ph = counter.add(req.resource)
    return (
        "SELECT column_name, data_type FROM information_schema.columns "
        f"WHERE table_name = {table_ph} AND table_schema = DATABASE() "
        "ORDER BY ordinal_position"
    )


def _indexes_sql(req: CapabilityRequest, counter: _ArgCounter) -> str:
    # Dialect-specific: SHOW INDEX returns a different result shape than PG's
    # pg_indexes (columns like Table, Key_name, Column_name, Non_unique, ...),
    # not the {indexname, indexdef} shape the Postgres plugin produces.
    table = quote_ident(req.resource)
    return f"SHOW INDEX FROM {table}"


def _list_resources_sql(req: CapabilityRequest, counter: _ArgCounter) -> str:
    return "SELECT table_name FROM information_schema.tables WHERE table_schema = DATABASE()"


def _list_databases_sql(req: CapabilityRequest, counter: _ArgCounter) -> str:
    return "SHOW DATABASES"


def _stats_sql(req: CapabilityRequest, counter: _ArgCounter) -> str:
    return (
        "SELECT table_schema, SUM(data_length + index_length) AS size "
        "FROM information_schema.tables WHERE table_schema = DATABASE() "
        "GROUP BY table_schema"
    )


_DIALECT = Dialect(
    name="MySQLPlugin",
    placeholder=lambda n: "%s",
    quote_ident=quote_ident,
    supports_returning=False,
    in_uses_array=False,
    delete_one_strategy="limit",
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
