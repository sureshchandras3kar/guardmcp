import pytest

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


# ── Data-trust signals v1: null_ratio / distinct_ratio / freshness ─────────


def test_null_ratio_surfaced_for_plain_field():
    inp = SemanticsInput(resource="user", fields={"notes": "string"},
        field_stats={"notes": FieldStat(count=100, null_count=25, distinct_count=80)})
    fs = A.analyze(inp).fields["notes"]
    assert fs.null_ratio == pytest.approx(0.25)
    assert fs.distinct_ratio == pytest.approx(0.8)


def test_null_ratio_none_when_no_stat():
    fs = A.analyze(SemanticsInput(resource="user", fields={"notes": "string"})).fields["notes"]
    assert fs.null_ratio is None and fs.distinct_ratio is None


def test_distinct_ratio_none_when_distinct_count_unknown():
    inp = SemanticsInput(resource="user", fields={"notes": "string"},
        field_stats={"notes": FieldStat(count=100, null_count=0, distinct_count=None)})
    fs = A.analyze(inp).fields["notes"]
    assert fs.null_ratio == 0.0
    assert fs.distinct_ratio is None


def test_freshness_surfaced_for_timestamp_role_field():
    inp = SemanticsInput(resource="user", fields={"updated_at": "date"},
        field_stats={"updated_at": FieldStat(
            count=10, min_value="2024-01-01T00:00:00", max_value="2025-06-01T00:00:00"
        )})
    fs = A.analyze(inp).fields["updated_at"]
    assert fs.role == ROLE_TIMESTAMP
    assert fs.oldest_value == "2024-01-01T00:00:00"
    assert fs.newest_value == "2025-06-01T00:00:00"


def test_freshness_none_for_non_timestamp_field():
    inp = SemanticsInput(resource="user", fields={"name": "string"},
        field_stats={"name": FieldStat(count=10, min_value="x", max_value="y")})
    fs = A.analyze(inp).fields["name"]
    assert fs.oldest_value is None and fs.newest_value is None


def test_masked_field_has_no_data_trust_signals():
    inp = SemanticsInput(
        resource="user", fields={"password": "masked"}, masked_fields=["password"],
        field_stats={"password": FieldStat(count=10, null_count=2, distinct_count=8)},
    )
    fs = A.analyze(inp).fields["password"]
    assert fs.null_ratio is None and fs.distinct_ratio is None
    assert fs.oldest_value is None and fs.newest_value is None


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
