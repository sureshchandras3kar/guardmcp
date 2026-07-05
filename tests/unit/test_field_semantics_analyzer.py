from guardmcp.core.context.models import (
    ROLE_ENUM,
    ROLE_FOREIGN,
    ROLE_NONE,
    ROLE_PII,
    ROLE_PRIMARY,
    ROLE_TENANT,
    ROLE_TIMESTAMP,
    FieldStat,
    SemanticsInput,
)
from guardmcp.core.context.semantics import FieldSemanticsAnalyzer

A = FieldSemanticsAnalyzer()


def test_id_is_primary():
    r = A.analyze(SemanticsInput(resource="user", fields={"_id": "objectId"}))
    assert r.fields["_id"].role == ROLE_PRIMARY and r.fields["_id"].confidence == 1.0


def test_edge_field_is_foreign_with_reference():
    inp = SemanticsInput(resource="orders", fields={"user_id": "objectId"},
        edges=[{"from_field": "user_id", "to_resource": "user", "confidence": 0.75}])
    fs = A.analyze(inp).fields["user_id"]
    assert fs.role == ROLE_FOREIGN and fs.references == "user" and fs.confidence == 0.75


def test_high_fanin_foreign_is_tenant_structurally():
    # product-neutral name proves structural (not name-based) detection
    inp = SemanticsInput(resource="orders", fields={"grp": "objectId"},
        edges=[{"from_field": "grp", "to_resource": "grpx", "confidence": 0.75}],
        fan_in={"grp": 5})
    fs = A.analyze(inp).fields["grp"]
    assert fs.role == ROLE_TENANT and fs.references == "grpx"


def test_date_type_is_timestamp():
    r = A.analyze(SemanticsInput(resource="user", fields={"xts": "date"}))
    assert r.fields["xts"].role == ROLE_TIMESTAMP


def test_low_cardinality_string_is_enum_with_values():
    inp = SemanticsInput(resource="user", fields={"st": "string"},
        field_stats={"st": FieldStat(count=100, distinct_count=2, sample_values=["A", "B"])})
    fs = A.analyze(inp).fields["st"]
    assert fs.role == ROLE_ENUM and set(fs.values) == {"A", "B"}


def test_unique_index_near_unique_is_primary():
    inp = SemanticsInput(resource="user", fields={"xref": "string"},
        indexes=[{"name": "xref_1", "key": [("xref", 1)], "unique": True}],
        field_stats={"xref": FieldStat(count=100, distinct_count=100)})
    assert A.analyze(inp).fields["xref"].role == ROLE_PRIMARY


def test_masked_field_is_pii_name_only():
    inp = SemanticsInput(resource="user", fields={"password": "masked"}, masked_fields=["password"])
    fs = A.analyze(inp).fields["password"]
    assert fs.role == ROLE_PII and fs.values is None


def test_masked_field_with_stats_still_pii_no_values():
    """Masked field with populated stats is still PII by name only, values remain None."""
    inp = SemanticsInput(
        resource="user",
        fields={"password": "masked"},
        masked_fields=["password"],
        field_stats={"password": FieldStat(count=10, distinct_count=2, sample_values=["x", "y"])}
    )
    fs = A.analyze(inp).fields["password"]
    assert fs.role == ROLE_PII and fs.values is None


def test_pii_name_sets_flag():
    fs = A.analyze(SemanticsInput(resource="user", fields={"email": "string"})).fields["email"]
    assert fs.pii is True


def test_plain_field_is_none():
    fs = A.analyze(SemanticsInput(resource="user", fields={"notes": "string"})).fields["notes"]
    assert fs.role == ROLE_NONE


def test_deterministic():
    inp = SemanticsInput(resource="user", fields={"_id": "objectId", "st": "string"},
        field_stats={"st": FieldStat(count=10, distinct_count=2, sample_values=["A", "B"])})
    assert A.analyze(inp).model_dump() == A.analyze(inp).model_dump()


def test_false_positives_candidate_mandate_not_timestamp():
    """Verify regex no longer matches 'candidate' or 'mandate' as timestamps."""
    # candidate and mandate should NOT be classified as timestamps
    values = ["A", "B", "C", "D", "E"]
    inp_candidate = SemanticsInput(
        resource="user",
        fields={"candidate": "string"},
        field_stats={"candidate": FieldStat(count=100, distinct_count=5, sample_values=values)}
    )
    fs_candidate = A.analyze(inp_candidate).fields["candidate"]
    assert fs_candidate.role == ROLE_ENUM, f"Expected ENUM, got {fs_candidate.role} for 'candidate'"

    inp_mandate = SemanticsInput(
        resource="user",
        fields={"mandate": "string"},
        field_stats={"mandate": FieldStat(count=100, distinct_count=5, sample_values=values)}
    )
    fs_mandate = A.analyze(inp_mandate).fields["mandate"]
    assert fs_mandate.role == ROLE_ENUM, f"Expected ENUM, got {fs_mandate.role} for 'mandate'"
