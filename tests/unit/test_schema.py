from bson import ObjectId

from guardmcp.plugins.mongodb.schema import apply_mask, infer_schema


def test_infer_basic_types():
    docs = [{"name": "Alice", "age": 30, "active": True, "score": 4.5}]
    schema = infer_schema(docs)
    assert schema["name"] == "string"
    assert schema["age"] == "integer"
    assert schema["active"] == "boolean"
    assert schema["score"] == "number"


def test_infer_objectid():
    docs = [{"_id": ObjectId(), "name": "x"}]
    schema = infer_schema(docs)
    assert schema["_id"] == "ObjectId"


def test_infer_mixed_types():
    docs = [{"val": 1}, {"val": "one"}]
    schema = infer_schema(docs)
    assert isinstance(schema["val"], list)
    assert "integer" in schema["val"]
    assert "string" in schema["val"]


def test_infer_null_field():
    docs = [{"name": "Alice", "notes": None}]
    schema = infer_schema(docs)
    assert schema["notes"] == "null"


def test_infer_merges_fields_across_docs():
    docs = [{"a": 1}, {"b": "x"}]
    schema = infer_schema(docs)
    assert "a" in schema
    assert "b" in schema


def test_apply_mask_hides_type():
    schema = {"name": "string", "email": "string", "age": "integer"}
    masked = apply_mask(schema, ["email"])
    assert masked["email"] == "masked"
    assert masked["name"] == "string"
    assert masked["age"] == "integer"


def test_apply_mask_empty_list():
    schema = {"name": "string"}
    assert apply_mask(schema, []) == schema


def test_infer_empty_docs():
    assert infer_schema([]) == {}
