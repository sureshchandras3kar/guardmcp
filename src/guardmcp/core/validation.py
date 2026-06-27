"""
Database-agnostic grounding/security helpers.

MongoDB-specific validation (operator/stage bans, pipeline introspection, error
sanitization) lives in plugins/mongodb/guard.py — core must stay backend-neutral.

Fix 3: collection_permitted()     — discovery tool filtering
Fix 4: JsonDict / parse_json_str  — AI sends filter as JSON string → coerce to dict
Fix 5: SafeLimit                  — hard cap on result size via Field constraint
Fix 8: raise_guard_error()        — include allowlist in every rejection message
"""

import json
from typing import Annotated, Any

from mcp.server.fastmcp.exceptions import ToolError
from pydantic import BeforeValidator, Field

# ── Fix 4 ─────────────────────────────────────────────────────────────────────


def _parse_json_or_pass(value: object) -> object:
    """Coerce a JSON-encoded string to dict/list. Non-strings pass through."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON: {exc}") from exc
    return value


def _coerce_none_sentinels(value: object) -> object:
    """Map '', 'null', 'none', 'undefined' → None for optional dict params."""
    _FALSY = frozenset({"", "null", "none", "undefined"})
    if isinstance(value, str) and value.strip().lower() in _FALSY:
        return None
    return value


# Fix 4 type aliases — use these for all dict tool parameters.
# BeforeValidators run in REVERSE order in Pydantic v2:
# _coerce_none_sentinels runs first (last listed = first applied),
# then _parse_json_or_pass converts any remaining JSON string.
JsonDict = Annotated[
    dict[str, Any] | None,
    BeforeValidator(_parse_json_or_pass),
    BeforeValidator(_coerce_none_sentinels),
]

JsonList = Annotated[
    list[Any] | None,
    BeforeValidator(_parse_json_or_pass),
    BeforeValidator(_coerce_none_sentinels),
]


# ── Fix 5 ─────────────────────────────────────────────────────────────────────
# Hard cap prevents AI from flooding the LLM context with huge result sets.
SafeLimit = Annotated[int, Field(ge=1, le=500, description="Max documents to return (1–500).")]


# ── Fix 8 ─────────────────────────────────────────────────────────────────────


def raise_guard_error(message: str, *, allowed: list[str] | None = None) -> None:
    """
    Fix 8: always include what IS allowed so AI can self-correct on retry.
    """
    if allowed:
        message = f"{message} Allowed values: {sorted(allowed)}."
    raise ToolError(message)


# ── Fix 3 helper ──────────────────────────────────────────────────────────────


def collection_permitted(name: str, allow: list[str], deny: list[str]) -> bool:
    """Fix 3 / AD-1: true if collection name passes policy allow/deny lists.

    Deny-by-default (secure-by-default). Semantics:
      * deny always wins (even over the "*" wildcard).
      * "*" in allow ⇒ all collections permitted (explicit "all").
      * name in allow ⇒ permitted.
      * empty or non-matching allow ⇒ DENIED.

    BREAKING (AD-1): an empty `allow` now means DENY-ALL. To permit every
    collection you must list ["*"] explicitly; previously an empty allow
    silently permitted everything (wide-open).
    """
    if name in deny:
        return False
    if "*" in allow:
        return True
    return name in allow
