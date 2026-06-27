"""Tests for aggregation-pipeline guards: cross-collection, masked-field, stage allow-list."""

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from guardmcp.plugins.mongodb.guard import (
    extract_pipeline_collections,
    find_masked_field_references,
    validate_pipeline_stages,
)


class TestExtractPipelineCollections:
    def test_lookup_from(self):
        pipeline = [
            {"$lookup": {"from": "payroll", "localField": "x", "foreignField": "y", "as": "z"}}
        ]
        assert extract_pipeline_collections(pipeline) == {"payroll"}

    def test_graph_lookup_from(self):
        pipeline = [
            {
                "$graphLookup": {
                    "from": "employees",
                    "startWith": "$m",
                    "connectFromField": "m",
                    "connectToField": "_id",
                    "as": "chain",
                }
            }
        ]
        assert extract_pipeline_collections(pipeline) == {"employees"}

    def test_union_with_string_form(self):
        pipeline = [{"$unionWith": "other_coll"}]
        assert extract_pipeline_collections(pipeline) == {"other_coll"}

    def test_union_with_object_coll_form(self):
        pipeline = [{"$unionWith": {"coll": "audit", "pipeline": []}}]
        assert extract_pipeline_collections(pipeline) == {"audit"}

    def test_nested_facet_sub_pipeline_lookup(self):
        pipeline = [{"$facet": {"branch": [{"$lookup": {"from": "secrets", "as": "s"}}]}}]
        assert extract_pipeline_collections(pipeline) == {"secrets"}


class TestFindMaskedFieldReferences:
    def test_email_reference_detected(self):
        pipeline = [{"$project": {"x": "$email"}}]
        assert find_masked_field_references(pipeline, ["email"]) == {"email"}

    def test_no_reference_returns_empty(self):
        pipeline = [{"$project": {"x": "$name"}}]
        assert find_masked_field_references(pipeline, ["email"]) == set()

    def test_nested_group_reference_detected(self):
        pipeline = [{"$group": {"_id": "$email", "n": {"$sum": 1}}}]
        assert find_masked_field_references(pipeline, ["email"]) == {"email"}


class TestValidatePipelineStages:
    def test_coll_stats_blocked(self):
        with pytest.raises(ToolError):
            validate_pipeline_stages([{"$collStats": {}}])

    def test_index_stats_blocked(self):
        with pytest.raises(ToolError):
            validate_pipeline_stages([{"$indexStats": {}}])

    def test_out_blocked(self):
        with pytest.raises(ToolError):
            validate_pipeline_stages([{"$out": "target"}])

    def test_merge_blocked(self):
        with pytest.raises(ToolError):
            validate_pipeline_stages([{"$merge": {"into": "x"}}])

    def test_allowed_stages_pass(self):
        validate_pipeline_stages(
            [
                {"$match": {"status": "active"}},
                {"$lookup": {"from": "orders", "as": "o"}},
                {"$unionWith": {"coll": "archive"}},
            ]
        )


class TestGuardAggregationViaExecutorDelegation:
    """P3: _guard_aggregation now reaches MongoDB pipeline knowledge THROUGH the
    active executor (referenced_collections / masked_field_references) instead of
    importing it directly. These confirm the DENIED decisions still fire."""

    def test_denies_lookup_to_denied_collection(self, pipeline):
        from guardmcp.core.models.domain import Action, DecisionStatus

        result = pipeline.evaluate(
            "test-agent",
            "customers",
            Action.AGGREGATE,
            {"pipeline": [{"$lookup": {"from": "payroll", "as": "p"}}]},
        )
        assert result.decision.status == DecisionStatus.DENIED
        assert "payroll" in result.decision.reason

    def test_denies_masked_field_reference(self, pipeline):
        from guardmcp.core.models.domain import Action, DecisionStatus

        result = pipeline.evaluate(
            "test-agent",
            "customers",
            Action.AGGREGATE,
            {"pipeline": [{"$project": {"x": "$email"}}]},
        )
        assert result.decision.status == DecisionStatus.DENIED
        assert "email" in result.decision.reason

    def test_clean_pipeline_not_denied_by_guard(self, pipeline):
        from guardmcp.core.models.domain import Action, DecisionStatus

        result = pipeline.evaluate(
            "test-agent",
            "customers",
            Action.AGGREGATE,
            {
                "pipeline": [
                    {"$match": {"status": "active"}},
                    {"$lookup": {"from": "orders", "as": "o"}},
                ]
            },
        )
        # guard does not object → falls through to normal policy (allowed)
        assert result.decision.status != DecisionStatus.DENIED
