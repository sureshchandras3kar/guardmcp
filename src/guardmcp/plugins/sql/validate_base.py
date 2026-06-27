"""
Shared SQL request validation for the relational plugins.

PostgreSQL and MySQL share IDENTICAL pre-translation guard logic: reject any
raw-SQL escape hatch, and require every identifier (resource, schema, filter
columns, projection, document keys, update keys, joined tables) to pass the
dialect's ``quote_ident`` allow-list. The ONLY dialect-specific dependency is
``quote_ident`` (Postgres double-quotes, MySQL backticks), so it is injected as
a callable here, mirroring how ``translate_base.py`` and ``cost.py`` already
factor the shared SQL logic.

These checks run BEFORE translation/execution and reject anything that cannot be
expressed as safe, parameterized SQL. Each plugin's ``validate.py`` is a thin
shim that binds its dialect ``quote_ident`` to ``validate_request`` /
``cross_resource_refs``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ...core.interfaces.capability import CapabilityRequest
from ...core.interfaces.errors import GuardValidationError
from .translate_base import _OPERATORS

# A dialect's identifier quoter; raises GuardValidationError on a bad identifier.
QuoteIdent = Callable[[str], str]

# Operators permitted inside a filter condition dict.
_ALLOWED_FILTER_OPERATORS: frozenset[str] = frozenset({*_OPERATORS, "$in"})

# Options keys that constitute a raw-SQL escape hatch and are always rejected.
_FORBIDDEN_OPTION_KEYS: frozenset[str] = frozenset({"raw_sql", "rawSql", "sql"})


def _validate_filter(filter_: dict[str, Any] | None, quote_ident: QuoteIdent) -> None:
    if not filter_:
        return
    if not isinstance(filter_, dict):
        raise GuardValidationError("filter must be an object")
    for col, cond in filter_.items():
        quote_ident(col)
        if isinstance(cond, dict):
            for op in cond:
                if op not in _ALLOWED_FILTER_OPERATORS:
                    raise GuardValidationError(
                        f"unsupported operator {op!r}; allowed: {sorted(_ALLOWED_FILTER_OPERATORS)}"
                    )


def _validate_keys(docs: list[dict[str, Any]] | None, quote_ident: QuoteIdent) -> None:
    if not docs:
        return
    for doc in docs:
        if not isinstance(doc, dict):
            raise GuardValidationError("each document must be an object")
        for col in doc:
            quote_ident(col)


def validate_request(req: CapabilityRequest, quote_ident: QuoteIdent) -> None:
    """Raise GuardValidationError if the request is unsafe for this backend."""
    # Reject any raw-SQL escape hatch outright.
    for key in req.options:
        if key in _FORBIDDEN_OPTION_KEYS:
            raise GuardValidationError(f"option {key!r} (raw SQL) is not permitted")

    # Resource identifier (optional for LIST_DATABASES/STATS where it is unused).
    if req.resource:
        quote_ident(req.resource)

    # Schema option, if present, must be a valid identifier.
    schema = req.options.get("schema")
    if schema is not None:
        quote_ident(schema)

    _validate_filter(req.filter, quote_ident)

    # Projection keys are column identifiers.
    if req.projection:
        for col in req.projection:
            quote_ident(col)

    # Document keys are column identifiers.
    _validate_keys(req.documents, quote_ident)

    # Update $set / flat keys are column identifiers.
    if req.update:
        set_doc = req.update.get("$set") if "$set" in req.update else req.update
        if isinstance(set_doc, dict):
            for col in set_doc:
                quote_ident(col)


def cross_resource_refs(req: CapabilityRequest, quote_ident: QuoteIdent) -> set[str]:
    """Return foreign resources referenced by the request.

    Requests are structured (no raw SQL), so by default there are none. We do
    support an optional structured ``options["joins"]`` list of table names so a
    policy engine can authorize each joined table; every entry is validated as an
    identifier.
    """
    joins = req.options.get("joins")
    if not joins:
        return set()
    if not isinstance(joins, (list, tuple)):
        raise GuardValidationError("options['joins'] must be a list of table names")
    refs: set[str] = set()
    for table in joins:
        quote_ident(table)
        refs.add(table)
    return refs
