"""
ObjectId coercion is now SCHEMA-DRIVEN (via marshal_filter), not blind.

Previously _coerce_objectids() coerced ANY 24-lowercase-hex string to ObjectId
anywhere in a filter, which produced a false positive: a legitimate 24-hex
STRING value (e.g. a git sha) on a string field was wrongly turned into an
ObjectId (the S-7 false-positive). The marshaller fixes this: a 24-hex string is
only coerced when the field's schema says objectId (or it's _id by convention).

These tests pin the NEW semantics. The blind helper is gone.
"""

from bson import ObjectId

from guardmcp.plugins.mongodb.marshal import marshal_filter

_HEX24 = "507f1f77bcf86cd799439011"


def test_blind_helper_is_removed():
    # The blind _coerce_objectids helper no longer exists — coercion is
    # schema-driven through marshal_filter.
    import guardmcp.plugins.mongodb.executor as executor_mod

    assert not hasattr(executor_mod, "_coerce_objectids")


def test_id_coerced_by_convention_without_schema():
    # _id is conventionally an ObjectId: a 24-hex _id is coerced even with no
    # type map.
    result = marshal_filter({"_id": _HEX24}, {})
    assert isinstance(result["_id"], ObjectId)
    assert str(result["_id"]) == _HEX24


def test_objectid_field_coerced_when_schema_says_objectid():
    result = marshal_filter({"owner_id": _HEX24}, {"owner_id": "objectId"})
    assert isinstance(result["owner_id"], ObjectId)


def test_s7_false_positive_fixed_hex_on_string_field_not_coerced():
    # The S-7 false positive: a 24-hex value on a STRING field must NOT be
    # coerced to an ObjectId.
    result = marshal_filter({"sha": _HEX24}, {"sha": "string"})
    assert result["sha"] == _HEX24
    assert not isinstance(result["sha"], ObjectId)


def test_unknown_field_passes_through_untouched():
    # No schema entry → no coercion, no error. A 24-hex value on an unknown
    # (non-_id) field is left as a plain string.
    result = marshal_filter({"refs": _HEX24}, {})
    assert result["refs"] == _HEX24


def test_non_hex_id_with_string_schema_left_unchanged():
    # A string-keyed collection: explicit string _id schema respects the string.
    result = marshal_filter({"_id": "user-123"}, {"_id": "string"})
    assert result["_id"] == "user-123"


def test_non_hex_id_without_schema_left_unchanged():
    # Best-effort _id coercion never fails loud: a non-hex _id with no schema
    # passes through unchanged (string-keyed collection).
    result = marshal_filter({"_id": "user-123"}, {})
    assert result["_id"] == "user-123"


def test_in_operator_coerces_each_objectid_element():
    result = marshal_filter({"owner_id": {"$in": [_HEX24, _HEX24]}}, {"owner_id": "objectId"})
    assert all(isinstance(v, ObjectId) for v in result["owner_id"]["$in"])
