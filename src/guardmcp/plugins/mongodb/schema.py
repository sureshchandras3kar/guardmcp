"""
Schema inference from sampled MongoDB documents.
Returns a simplified type map: field → type string.
Masked fields are shown as "masked" — never expose their real type.
"""

from datetime import datetime
from typing import Any

from bson import Decimal128, Int64, ObjectId


def _canonical_bson_type(v: Any) -> str | None:
    """Map a RAW bson/python value to a canonical BSON type token.

    Tokens: objectId, date, decimal, int, long, double, string, bool, array,
    object. Returns None for null/unknown so callers can skip ambiguous fields.

    Must run on RAW documents (before _bson_to_json), since serialization turns
    ObjectId/datetime/Decimal128 into strings/numbers and loses the BSON type.
    """
    if v is None:
        return None
    if isinstance(v, bool):  # bool before int — bool is an int subclass
        return "bool"
    if isinstance(v, ObjectId):
        return "objectId"
    if isinstance(v, datetime):
        return "date"
    if isinstance(v, Decimal128):
        return "decimal"
    if isinstance(v, Int64):
        return "long"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "double"
    if isinstance(v, str):
        return "string"
    if isinstance(v, (list, tuple)):
        return "array"
    if isinstance(v, dict):
        return "object"
    return None


def build_type_map(raw_docs: list[dict[str, Any]]) -> dict[str, str]:
    """Per-collection canonical BSON type map: top-level field -> type token.

    Built from RAW sampled documents (NOT JSON-serialized). A field is only
    included when every non-null sample agrees on a single canonical type — a
    polymorphic field (mixed types across the sample) is OMITTED so the
    marshaller treats it as unknown and passes values through (conservative:
    never coerce/reject a field whose type is ambiguous).
    """
    seen: dict[str, set[str]] = {}
    for doc in raw_docs:
        if not isinstance(doc, dict):
            continue
        for k, v in doc.items():
            tok = _canonical_bson_type(v)
            if tok is not None:
                seen.setdefault(k, set()).add(tok)
    return {field: next(iter(toks)) for field, toks in seen.items() if len(toks) == 1}


def _type_label(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int):
        return "integer"
    if isinstance(v, float):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "array"
    if isinstance(v, dict):
        return "object"
    if isinstance(v, ObjectId):
        return "ObjectId"
    return type(v).__name__


def infer_schema(docs: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Infer field types from a sample of documents.
    Returns {field: type} or {field: [type1, type2]} when multiple types observed.
    """
    fields: dict[str, set[str]] = {}
    for doc in docs:
        for k, v in doc.items():
            fields.setdefault(k, set()).add(_type_label(v))

    schema: dict[str, Any] = {}
    for field, types in sorted(fields.items()):
        sorted_types = sorted(types)
        schema[field] = sorted_types[0] if len(sorted_types) == 1 else sorted_types

    return schema


def apply_mask(schema: dict[str, Any], mask_fields: list[str]) -> dict[str, Any]:
    """Replace type of masked fields with 'masked' so AI knows the field exists but can't infer type."""  # noqa: E501
    masked = set(mask_fields)
    return {k: "masked" if k in masked else v for k, v in schema.items()}


_ENUM_TRACK_CAP = 50
_ENUM_VALUES_CAP = 20


def build_field_stats(raw_docs: list[dict], mask_fields: list[str]) -> dict[str, dict]:
    """Per-field sample stats from RAW sampled docs. Masking-aware: masked fields
    record NO values (distinct_count/sample_values/min_value/max_value = None).
    Absent fields count as null. Only hashable scalars (str/int/float/bool)
    contribute to distinct/values; fields with >_ENUM_TRACK_CAP distinct overflow
    to distinct_count=None. Datetime fields separately track min/max sampled
    value (freshness signal) — kept out of the enum-tracking set since a
    datetime isn't a useful enum value."""
    masked = set(mask_fields)
    total = len(raw_docs)
    present: dict[str, int] = {}
    nulls: dict[str, int] = {}
    vals: dict[str, set] = {}
    overflow: dict[str, bool] = {}
    date_range: dict[str, list] = {}  # field -> [min, max]
    for doc in raw_docs:
        if not isinstance(doc, dict):
            continue
        for k, v in doc.items():
            present[k] = present.get(k, 0) + 1
            if v is None:
                nulls[k] = nulls.get(k, 0) + 1
                continue
            if k in masked:
                continue
            if isinstance(v, datetime):
                lo, hi = date_range.get(k, (v, v))
                date_range[k] = [min(lo, v), max(hi, v)]
                continue
            if overflow.get(k):
                continue
            if isinstance(v, (str, int, float, bool)):
                s = vals.setdefault(k, set())
                s.add(v)
                if len(s) > _ENUM_TRACK_CAP:
                    overflow[k] = True
                    vals[k] = set()
    out: dict[str, dict] = {}
    for k in present:
        null_count = nulls.get(k, 0) + (total - present[k])
        if k in masked or overflow.get(k):
            distinct_count = None
            sample_values = None
        else:
            s = vals.get(k, set())
            distinct_count = len(s)
            sample_values = (
                sorted(s, key=lambda x: str(x))[:_ENUM_VALUES_CAP]
                if 0 < distinct_count <= _ENUM_VALUES_CAP
                else None
            )
        rng = date_range.get(k) if k not in masked else None
        out[k] = {
            "count": total,
            "null_count": null_count,
            "distinct_count": distinct_count,
            "sample_values": sample_values,
            "min_value": rng[0] if rng else None,
            "max_value": rng[1] if rng else None,
        }
    return out
