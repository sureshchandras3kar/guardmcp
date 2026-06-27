"""Tests for all 8 grounding/security fixes in validation.py."""

import pytest
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import BaseModel, ValidationError

from guardmcp.core.validation import (
    JsonDict,
    SafeLimit,
    collection_permitted,
    raise_guard_error,
)
from guardmcp.plugins.mongodb.guard import (
    has_dangerous_operators,
    sanitize_mongo_error,
    validate_filter,
    validate_pipeline_stages,
)

# ── Fix 2: dangerous operator detection ───────────────────────────────────────


class TestHasDangerousOperators:
    def test_clean_filter_returns_false(self):
        assert has_dangerous_operators({"name": "Alice", "age": {"$gt": 18}}) is False

    def test_where_top_level(self):
        assert has_dangerous_operators({"$where": "this.age > 18"}) is True

    def test_function_nested(self):
        assert has_dangerous_operators({"a": {"$function": {}}}) is True

    def test_accumulator_in_list(self):
        assert has_dangerous_operators([{"$accumulator": {}}]) is True

    def test_out_stage(self):
        assert has_dangerous_operators({"$out": "target_col"}) is True

    def test_merge_stage(self):
        assert has_dangerous_operators({"$merge": {"into": "x"}}) is True

    def test_safe_dollar_operators_pass(self):
        assert has_dangerous_operators({"age": {"$gte": 18, "$lte": 65}}) is False
        assert has_dangerous_operators({"status": {"$in": ["active", "pending"]}}) is False

    def test_empty_dict(self):
        assert has_dangerous_operators({}) is False


class TestValidateFilter:
    def test_valid_filter_passes(self):
        validate_filter({"status": "active"})  # no exception

    def test_not_a_dict_raises(self):
        with pytest.raises(ToolError, match="must be a JSON object"):
            validate_filter("status=active")

    def test_dangerous_operator_raises(self):
        with pytest.raises(ToolError, match="disallowed operator"):
            validate_filter({"$where": "1==1"})

    def test_error_lists_banned_operators(self):
        with pytest.raises(ToolError, match=r"\$where"):
            validate_filter({"$where": "x"})


# ── Fix 7: pipeline stage validation ──────────────────────────────────────────


class TestValidatePipelineStages:
    def test_valid_pipeline_passes(self):
        validate_pipeline_stages(
            [
                {"$match": {"status": "active"}},
                {"$group": {"_id": "$status", "count": {"$sum": 1}}},
            ]
        )

    def test_out_blocked(self):
        with pytest.raises(ToolError, match=r"\$out"):
            validate_pipeline_stages([{"$out": "target"}])

    def test_merge_blocked(self):
        with pytest.raises(ToolError, match=r"\$merge"):
            validate_pipeline_stages([{"$merge": {"into": "x"}}])

    def test_function_in_stage_blocked(self):
        with pytest.raises(ToolError, match="disallowed operator"):
            validate_pipeline_stages([{"$addFields": {"x": {"$function": {}}}}])

    def test_malformed_stage_rejected(self):
        with pytest.raises(ToolError, match="single-key"):
            validate_pipeline_stages(["not a dict"])

    def test_multi_key_stage_rejected(self):
        with pytest.raises(ToolError, match="single-key"):
            validate_pipeline_stages([{"$match": {}, "$sort": {}}])


# ── Fix 4: JsonDict coercion ───────────────────────────────────────────────────


class _Model(BaseModel):
    filter: JsonDict = None
    limit: SafeLimit = 20


class TestJsonDict:
    def test_dict_passes_through(self):
        m = _Model(filter={"name": "Alice"})
        assert m.filter == {"name": "Alice"}

    def test_json_string_coerced(self):
        m = _Model(filter='{"name": "Alice"}')
        assert m.filter == {"name": "Alice"}

    def test_null_string_becomes_none(self):
        m = _Model(filter="null")
        assert m.filter is None

    def test_empty_string_becomes_none(self):
        m = _Model(filter="")
        assert m.filter is None

    def test_undefined_string_becomes_none(self):
        m = _Model(filter="undefined")
        assert m.filter is None

    def test_invalid_json_raises(self):
        with pytest.raises(ValidationError):
            _Model(filter="{bad json")


# ── Fix 5: SafeLimit ───────────────────────────────────────────────────────────


class TestSafeLimit:
    def test_default_is_20(self):
        assert _Model().limit == 20

    def test_valid_limit_accepted(self):
        assert _Model(limit=100).limit == 100

    def test_zero_rejected(self):
        with pytest.raises(ValidationError):
            _Model(limit=0)

    def test_above_500_rejected(self):
        with pytest.raises(ValidationError):
            _Model(limit=501)

    def test_boundary_500_accepted(self):
        assert _Model(limit=500).limit == 500


# ── Fix 6: error sanitization ─────────────────────────────────────────────────


class TestSanitizeMongoError:
    def test_collection_not_found(self):
        msg = sanitize_mongo_error(Exception("collection 'foo' not found"))
        assert "mongodb_list_collections" in msg
        assert "foo" not in msg  # raw collection name not leaked

    def test_timeout(self):
        msg = sanitize_mongo_error(Exception("operation timed out"))
        assert "timed out" in msg

    def test_generic(self):
        msg = sanitize_mongo_error(Exception("some internal pymongo error"))
        assert "Query failed" in msg
        assert "pymongo" not in msg


# ── Fix 8: allowlist in errors ─────────────────────────────────────────────────


class TestRaiseGuardError:
    def test_message_only(self):
        with pytest.raises(ToolError, match="action not permitted"):
            raise_guard_error("action not permitted")

    def test_allowed_list_included(self):
        with pytest.raises(ToolError, match="find"):
            raise_guard_error("action not permitted", allowed=["find", "count"])


# ── Fix 3: collection_permitted ───────────────────────────────────────────────


class TestCollectionPermitted:
    def test_in_allow_list(self):
        assert collection_permitted("customers", allow=["customers", "orders"], deny=[]) is True

    def test_not_in_allow_list(self):
        assert collection_permitted("payroll", allow=["customers", "orders"], deny=[]) is False

    def test_in_deny_list(self):
        assert collection_permitted("payroll", allow=[], deny=["payroll"]) is False

    def test_deny_beats_allow(self):
        assert collection_permitted("customers", allow=["customers"], deny=["customers"]) is False

    def test_empty_allow_means_deny_all(self):
        # AD-1: deny-by-default — empty allow now DENIES (was wide-open).
        assert collection_permitted("anything", allow=[], deny=[]) is False

    def test_wildcard_allow_permits_all(self):
        assert collection_permitted("anything", allow=["*"], deny=[]) is True

    def test_deny_beats_wildcard(self):
        assert collection_permitted("payroll", allow=["*"], deny=["payroll"]) is False
