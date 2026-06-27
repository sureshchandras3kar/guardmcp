"""Shared SQL translation core for relational plugins (PostgreSQL, MySQL, ...).

This package factors the injection-safe, dialect-agnostic translation logic out of
the per-backend plugins. Each backend defines a thin :class:`Dialect` describing
its deltas (placeholder style, identifier quoting, RETURNING support, single-row
DELETE strategy, catalog queries) and delegates to :class:`SqlTranslator`.

The security invariants live here, ONCE:

1. Identifiers are validated against ``^[A-Za-z_][A-Za-z0-9_]*$`` (per dot part,
   at most ``schema.table``) before being placed into SQL text; invalid
   identifiers raise :class:`GuardValidationError`.
2. Values are NEVER string-formatted into SQL — they are always emitted as
   dialect placeholders and collected into a positional ``args`` list.
"""

from .translate_base import (
    Dialect,
    SqlTranslator,
    Translated,
    validate_ident,
)

__all__ = [
    "Dialect",
    "SqlTranslator",
    "Translated",
    "validate_ident",
]
