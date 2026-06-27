"""Unit tests for the MongoDB filter type-marshalling layer (marshal_filter)."""

from datetime import datetime

import pytest
from bson import Decimal128, ObjectId

from guardmcp.core.interfaces.errors import GuardValidationError
from guardmcp.plugins.mongodb.marshal import MarshalError, marshal_filter

_HEX24 = "507f1f77bcf86cd799439011"


# ── Layer 2: schema-driven coercion ───────────────────────────────────────────


def test_date_string_coerced_on_date_field():
    out = marshal_filter({"created_at": "2026-06-01"}, {"created_at": "date"})
    assert isinstance(out["created_at"], datetime)
    assert out["created_at"].year == 2026 and out["created_at"].month == 6


def test_date_operator_operands_coerced():
    out = marshal_filter(
        {"created_at": {"$gte": "2026-06-01", "$lt": "2026-07-01"}},
        {"created_at": "date"},
    )
    assert isinstance(out["created_at"]["$gte"], datetime)
    assert isinstance(out["created_at"]["$lt"], datetime)


def test_datetime_with_time_component_coerced():
    out = marshal_filter({"ts": {"$gte": "2026-06-01 13:45:00"}}, {"ts": "date"})
    assert out["ts"]["$gte"] == datetime(2026, 6, 1, 13, 45, 0)


def test_objectid_field_coerced():
    out = marshal_filter({"owner": _HEX24}, {"owner": "objectId"})
    assert isinstance(out["owner"], ObjectId)


def test_decimal_field_coerced():
    out = marshal_filter({"amount": "10.50"}, {"amount": "decimal"})
    assert isinstance(out["amount"], Decimal128)
    assert str(out["amount"]) == "10.50"


def test_int_field_coerced_from_string():
    out = marshal_filter({"qty": "42"}, {"qty": "int"})
    assert out["qty"] == 42 and isinstance(out["qty"], int)


def test_in_list_each_element_coerced():
    out = marshal_filter(
        {"created_at": {"$in": ["2026-06-01", "2026-06-02"]}},
        {"created_at": "date"},
    )
    assert all(isinstance(v, datetime) for v in out["created_at"]["$in"])


def test_already_correct_type_passthrough():
    dt = datetime(2026, 6, 1)
    out = marshal_filter({"created_at": dt}, {"created_at": "date"})
    assert out["created_at"] is dt


# ── Layer 3: extended-JSON escape hatch (schema-independent) ───────────────────


def test_date_literal_escape_hatch_no_schema():
    out = marshal_filter({"x": {"$date": "2026-06-01"}}, {})
    assert isinstance(out["x"], datetime)


def test_oid_literal_escape_hatch_no_schema():
    out = marshal_filter({"x": {"$oid": _HEX24}}, {})
    assert isinstance(out["x"], ObjectId)


def test_decimal_literal_escape_hatch():
    out = marshal_filter({"x": {"$decimal": "3.14"}}, {})
    assert isinstance(out["x"], Decimal128)


def test_int_literal_escape_hatch():
    out = marshal_filter({"x": {"$int": 7}}, {})
    assert out["x"] == 7


def test_escape_hatch_wins_inside_operator():
    out = marshal_filter({"x": {"$gte": {"$date": "2026-06-01"}}}, {})
    assert isinstance(out["x"]["$gte"], datetime)


# ── Layer 1: fail loud on impossible coercion ─────────────────────────────────


def test_unparseable_date_raises_marshal_error():
    with pytest.raises(MarshalError) as ei:
        marshal_filter({"created_at": "banana"}, {"created_at": "date"})
    assert "created_at" in str(ei.value)
    assert "date" in str(ei.value).lower()


def test_marshal_error_is_guard_validation_error():
    # Pipeline catches GuardValidationError to map to TYPE_MISMATCH.
    assert issubclass(MarshalError, GuardValidationError)


def test_bad_objectid_on_objectid_field_raises():
    with pytest.raises(MarshalError):
        marshal_filter({"owner": "not-an-oid"}, {"owner": "objectId"})


def test_bad_int_raises():
    with pytest.raises(MarshalError):
        marshal_filter({"qty": "abc"}, {"qty": "int"})


# ── Conservatism: do not over-reject ──────────────────────────────────────────


def test_unknown_field_passthrough():
    out = marshal_filter({"weird": "anything", "n": 5}, {})
    assert out == {"weird": "anything", "n": 5}


def test_string_field_string_value_no_error():
    out = marshal_filter({"status": "active"}, {"status": "string"})
    assert out["status"] == "active"


def test_hex_on_string_field_not_coerced():
    out = marshal_filter({"sha": _HEX24}, {"sha": "string"})
    assert out["sha"] == _HEX24 and not isinstance(out["sha"], ObjectId)


# ── Logical operators recurse ──────────────────────────────────────────────────


def test_and_or_recurse_into_subfilters():
    out = marshal_filter(
        {"$and": [{"created_at": {"$gte": "2026-06-01"}}, {"status": "active"}]},
        {"created_at": "date", "status": "string"},
    )
    assert isinstance(out["$and"][0]["created_at"]["$gte"], datetime)
    assert out["$and"][1]["status"] == "active"


# ── Structural operators left intact ──────────────────────────────────────────


def test_exists_operator_untouched():
    out = marshal_filter({"created_at": {"$exists": True}}, {"created_at": "date"})
    assert out["created_at"] == {"$exists": True}


def test_non_dict_filter_passthrough():
    assert marshal_filter(None, {"a": "date"}) is None
