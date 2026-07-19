from guardmcp.core.context.models import (
    ROLE_FOREIGN,
    ROLE_NONE,
    FieldSemantics,
    FieldStat,
    SemanticsInput,
    SemanticsResult,
)


def test_field_stat_defaults():
    s = FieldStat(count=10)
    assert s.null_count == 0 and s.distinct_count is None and s.sample_values is None


def test_field_semantics_defaults():
    fs = FieldSemantics(role=ROLE_NONE)
    assert fs.confidence == 0.0 and fs.pii is False and fs.references is None and fs.values is None


def test_semantics_input_defaults():
    inp = SemanticsInput(resource="user", fields={"_id": "objectId"})
    assert inp.indexes == [] and inp.edges == [] and inp.fan_in == {} and inp.masked_fields == []


def test_semantics_result_holds_map():
    r = SemanticsResult(fields={"user_id": FieldSemantics(role=ROLE_FOREIGN, references="user")})
    assert r.fields["user_id"].references == "user"
