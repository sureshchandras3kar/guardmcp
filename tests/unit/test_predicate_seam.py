"""#2 seam: structured predicate AST field + lowering to the Mongo-operator
filter dialect. (Full native compilation is v2 work — this is the seam.)"""

import pytest

from guardmcp.core.interfaces.capability import (
    Capability,
    CapabilityRequest,
    compile_predicate_to_filter,
)


def test_predicate_field_present_and_optional():
    req = CapabilityRequest(capability=Capability.READ)
    assert req.predicate is None
    req2 = CapabilityRequest(
        capability=Capability.READ, predicate={"field": "age", "op": "gt", "value": 18}
    )
    assert req2.predicate == {"field": "age", "op": "gt", "value": 18}


def test_lower_leaf_eq_default():
    assert compile_predicate_to_filter({"field": "name", "value": "neo"}) == {"name": "neo"}
    assert compile_predicate_to_filter({"field": "name", "op": "eq", "value": "neo"}) == {
        "name": "neo"
    }


def test_lower_leaf_operators():
    assert compile_predicate_to_filter({"field": "age", "op": "gt", "value": 18}) == {
        "age": {"$gt": 18}
    }
    assert compile_predicate_to_filter({"field": "tier", "op": "in", "value": ["a", "b"]}) == {
        "tier": {"$in": ["a", "b"]}
    }


def test_lower_and():
    out = compile_predicate_to_filter(
        {
            "and": [
                {"field": "age", "op": "gte", "value": 18},
                {"field": "active", "value": True},
            ]
        }
    )
    assert out == {"$and": [{"age": {"$gte": 18}}, {"active": True}]}


def test_lower_or():
    out = compile_predicate_to_filter(
        {
            "or": [
                {"field": "role", "value": "admin"},
                {"field": "level", "op": "lt", "value": 3},
            ]
        }
    )
    assert out == {"$or": [{"role": "admin"}, {"level": {"$lt": 3}}]}


def test_lower_rejects_unknown_op():
    with pytest.raises(ValueError):
        compile_predicate_to_filter({"field": "x", "op": "regex", "value": ".*"})


def test_lower_rejects_malformed():
    with pytest.raises(ValueError):
        compile_predicate_to_filter({"op": "gt", "value": 1})  # no field
