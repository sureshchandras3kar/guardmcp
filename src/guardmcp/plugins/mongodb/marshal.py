"""
Type-marshalling at the MongoDB filter boundary.

JSON (what an LLM agent emits) cannot express BSON types: a date is a string,
an ObjectId is a 24-hex string, a Decimal128 is a number/string. A filter like
``{"created_at": {"$gte": "2026-06-01"}}`` therefore compares a STRING against a
BSON ``date`` field and silently matches nothing — the worst failure mode for an
agent, because an empty result looks like a legitimate "no rows".

This module closes that gap with three cooperating layers:

* **Layer 3 — extended-JSON escape hatch (always wins, schema-independent):**
  explicit typed literals ``{"$date": "<iso>"}``, ``{"$oid": "<24hex>"}``,
  ``{"$decimal": "<num>"}``, ``{"$int": n}``, ``{"$long": n}`` are honored
  anywhere a value appears and converted to the corresponding BSON type. These
  are GuardMCP filter-value conventions consumed here; they never reach Mongo as
  literal keys.

* **Layer 2 — schema-driven coercion:** given a per-collection ``type_map``
  (field -> canonical BSON type token), string/number operands on a typed field
  are coerced to that type (date string -> datetime, 24-hex -> ObjectId, etc.).
  ``_id`` is special-cased to attempt ObjectId coercion even without a schema.

* **Layer 1 — fail loud:** when a field's type is KNOWN and the value cannot be
  coerced to it (``created_at`` is a date but the value is ``"banana"``), raise
  :class:`MarshalError` with an actionable message instead of passing an
  un-matchable value to Mongo. The pipeline maps this to ``TYPE_MISMATCH``.

Conservatism is deliberate: unknown fields, polymorphic fields, and
already-correct types pass through untouched. A false ``TYPE_MISMATCH`` is worse
than a passthrough, so coercion only fails when it is unambiguously impossible.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from bson import Decimal128, ObjectId

from ...core.interfaces.errors import TypeMarshalError

_OBJECTID_RE = __import__("re").compile(r"^[0-9a-f]{24}$")

# MongoDB filter operators whose operand(s) are field VALUES (and so should be
# marshalled against the field's type). $in/$nin take a list of operands.
_VALUE_OPERATORS: frozenset[str] = frozenset({"$eq", "$ne", "$gt", "$gte", "$lt", "$lte"})
_LIST_OPERATORS: frozenset[str] = frozenset({"$in", "$nin"})
# Logical operators take a list of sub-filters (each a full filter dict).
_LOGICAL_OPERATORS: frozenset[str] = frozenset({"$and", "$or", "$nor"})

# Sentinel token for the schema-less _id case: try ObjectId on a 24-hex string,
# but pass non-hex strings through untouched (string-keyed collections) rather
# than failing loud. A schema that says _id is 'objectId' uses the strict token.
_ID_BEST_EFFORT = "_id_best_effort"


class MarshalError(TypeMarshalError):
    """A filter value cannot be coerced to the field's known BSON type.

    Raised by :func:`marshal_filter`. Subclasses the core
    :class:`TypeMarshalError` so the database-agnostic pipeline maps it to the
    ``TYPE_MISMATCH`` error code (agent-facing message surfaced verbatim) rather
    than sanitizing it like a generic backend validation error.
    """


# ── Scalar coercers ──────────────────────────────────────────────────────────


def _parse_iso_datetime(s: str) -> datetime:
    """Parse an ISO-ish date/datetime string. dateutil-free.

    Accepts 'YYYY-MM-DD', 'YYYY-MM-DD HH:MM:SS[.ffffff]', and
    'YYYY-MM-DDTHH:MM:SS[.ffffff]' (with optional offset). Raises ValueError
    when none of the supported forms parse.
    """
    s = s.strip()
    # datetime.fromisoformat handles both 'T' and ' ' separators (3.11+) and
    # plain dates; normalize a trailing 'Z' which older fromisoformat rejects.
    candidate = s[:-1] + "+00:00" if s.endswith("Z") else s
    try:
        return datetime.fromisoformat(candidate)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise ValueError(f"not an ISO date: {s!r}")


def _coerce_date(value: Any, field: str) -> Any:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return _parse_iso_datetime(value)
        except ValueError as err:
            raise MarshalError(
                f"filter field '{field}' expects a date; got {value!r}. "
                "Pass an ISO date (YYYY-MM-DD) or an extended-JSON literal "
                '{"$date": "..."}.'
            ) from err
    raise MarshalError(
        f"filter field '{field}' expects a date; got {type(value).__name__}. "
        'Pass an ISO date string (YYYY-MM-DD) or {"$date": "..."}.'
    )


def _coerce_objectid(value: Any, field: str) -> Any:
    if isinstance(value, ObjectId):
        return value
    if isinstance(value, str) and _OBJECTID_RE.match(value):
        try:
            return ObjectId(value)
        except Exception:  # pragma: no cover - regex already guards validity
            pass
    raise MarshalError(
        f"filter field '{field}' expects an ObjectId; got {value!r}. "
        'Pass a 24-character hex string or {"$oid": "<24hex>"}.'
    )


def _coerce_decimal(value: Any, field: str) -> Any:
    if isinstance(value, Decimal128):
        return value
    if isinstance(value, bool):
        raise MarshalError(f"filter field '{field}' expects a decimal; got a boolean.")
    if isinstance(value, (int, float, str)):
        try:
            return Decimal128(Decimal(str(value)))
        except (InvalidOperation, ValueError) as err:
            raise MarshalError(
                f"filter field '{field}' expects a decimal; got {value!r}. "
                'Pass a number, numeric string, or {"$decimal": "<num>"}.'
            ) from err
    raise MarshalError(f"filter field '{field}' expects a decimal; got {type(value).__name__}.")


def _coerce_int(value: Any, field: str) -> Any:
    if isinstance(value, bool):
        raise MarshalError(f"filter field '{field}' expects an integer; got a boolean.")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError as err:
            raise MarshalError(
                f"filter field '{field}' expects an integer; got {value!r}. "
                'Pass an integer or {"$int": n} / {"$long": n}.'
            ) from err
    raise MarshalError(f"filter field '{field}' expects an integer; got {value!r}.")


# Canonical type token -> scalar coercer. Tokens are the ones a type map emits
# (see build_type_map). 'string'/'bool'/'double'/'array'/'object'/'null' have no
# coercer: a JSON value already matches, so we never touch them.
def _coerce_objectid_best_effort(value: Any, field: str) -> Any:
    """Schema-less _id coercion: 24-hex -> ObjectId, anything else untouched.

    Mirrors the conventional case (``_id`` is an ObjectId) without failing loud
    on string-keyed collections where the schema is unknown.
    """
    if isinstance(value, str) and _OBJECTID_RE.match(value):
        try:
            return ObjectId(value)
        except Exception:  # pragma: no cover
            return value
    return value


_COERCERS = {
    "date": _coerce_date,
    "objectId": _coerce_objectid,
    "decimal": _coerce_decimal,
    "int": _coerce_int,
    "long": _coerce_int,
    _ID_BEST_EFFORT: _coerce_objectid_best_effort,
}


# ── Extended-JSON escape hatch (Layer 3) ──────────────────────────────────────


def _try_extended_json(value: Any) -> tuple[bool, Any]:
    """If ``value`` is a typed-literal escape hatch, return (True, converted).

    Recognizes single-key dicts ``{"$date": ...}``, ``{"$oid": ...}``,
    ``{"$decimal": ...}``, ``{"$int": ...}``, ``{"$long": ...}``. These always
    win over schema-driven coercion and need no type map.
    """
    if not isinstance(value, dict) or len(value) != 1:
        return False, None
    ((key, inner),) = value.items()
    if key == "$date":
        return True, _coerce_date(inner, "$date")
    if key == "$oid":
        return True, _coerce_objectid(inner, "$oid")
    if key == "$decimal":
        return True, _coerce_decimal(inner, "$decimal")
    if key in ("$int", "$long"):
        return True, _coerce_int(inner, key)
    return False, None


# ── Recursive filter walk ──────────────────────────────────────────────────────


def _marshal_operand(value: Any, type_token: str | None, field: str) -> Any:
    """Marshal a single operand for ``field`` whose known type is ``type_token``.

    Honors the extended-JSON escape hatch first (schema-independent), then
    applies schema-driven coercion when a coercer exists for the token.
    """
    matched, converted = _try_extended_json(value)
    if matched:
        return converted
    if type_token is None:
        return value
    coercer = _COERCERS.get(type_token)
    if coercer is None:
        return value
    return coercer(value, field)


def _marshal_field_value(value: Any, type_token: str | None, field: str) -> Any:
    """Marshal the value side of a ``field: value`` filter clause.

    The value may be a bare operand, an operator dict ({"$gte": ...}), or a mix.
    Operator keys are preserved; their operands are marshalled against the
    field's type. Non-operator dicts are treated as a nested/embedded equality
    document and passed through (operand coercion still applies to escape-hatch
    literals inside).
    """
    # Operator dict: marshal each operand, keep operator keys intact.
    if isinstance(value, dict) and any(k.startswith("$") for k in value):
        # First, the whole dict might itself be an escape-hatch literal.
        matched, converted = _try_extended_json(value)
        if matched:
            return converted
        out: dict[str, Any] = {}
        for op, operand in value.items():
            if op in _LIST_OPERATORS and isinstance(operand, list):
                out[op] = [_marshal_operand(item, type_token, field) for item in operand]
            elif op in _VALUE_OPERATORS:
                out[op] = _marshal_operand(operand, type_token, field)
            else:
                # Unknown/structural operator ($exists, $regex, $type, ...):
                # leave operand untouched (still honor escape-hatch literals).
                m, conv = _try_extended_json(operand)
                out[op] = conv if m else operand
        return out
    return _marshal_operand(value, type_token, field)


def marshal_filter(filter_: Any, type_map: dict[str, str] | None) -> Any:
    """Return ``filter_`` with values coerced to their fields' BSON types.

    ``type_map`` maps top-level field name -> canonical type token
    (objectId/date/decimal/int/long/string/bool/double/array/object). ``None``
    or ``{}`` means "no schema known" — only ``_id`` and explicit escape-hatch
    literals are coerced; everything else passes through.

    Raises :class:`MarshalError` when a field's type is known and a value cannot
    be coerced to it.
    """
    type_map = type_map or {}
    if not isinstance(filter_, dict):
        return filter_

    out: dict[str, Any] = {}
    for field, value in filter_.items():
        if field in _LOGICAL_OPERATORS and isinstance(value, list):
            # $and/$or/$nor: each element is a full sub-filter.
            out[field] = [marshal_filter(sub, type_map) for sub in value]
            continue
        if field.startswith("$"):
            # Top-level non-logical operator (rare): pass through, but still
            # honor escape-hatch literals nested inside.
            out[field] = _marshal_field_value(value, None, field)
            continue

        token = type_map.get(field)
        # _id special case: conventionally an ObjectId. With no schema, attempt
        # best-effort ObjectId coercion (24-hex only, never fail loud) so a
        # string-keyed collection still works. An explicit 'string' schema
        # respects the string _id; an explicit 'objectId' schema fails loud.
        if token is None and field == "_id":
            token = _ID_BEST_EFFORT
        elif field == "_id" and token == "string":
            token = None  # respect explicit string _id

        out[field] = _marshal_field_value(value, token, field)

    return out
