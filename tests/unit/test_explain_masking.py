"""S-1: EXPLAIN plan masking via GuardPipeline._build_success."""

from guardmcp.core.masking.masker import MASK_VALUE
from guardmcp.core.models.domain import Action
from guardmcp.core.policy.models import Policy


def _build_success(pipeline, raw, action, policy):
    return pipeline._build_success(raw, action, policy)


def test_explain_masks_filter_literals(pipeline):
    policy = Policy(agent="a", mask_fields=["password"])
    raw = {"queryPlanner": {"parsedQuery": {"password": {"$eq": "secret"}}}}
    result = _build_success(pipeline, raw, Action.EXPLAIN, policy)
    assert result["status"] == "success"
    parsed = result["data"]["queryPlanner"]["parsedQuery"]
    assert parsed["password"] == MASK_VALUE


def test_explain_without_mask_fields_unchanged(pipeline):
    policy = Policy(agent="a", mask_fields=[])
    raw = {"queryPlanner": {"parsedQuery": {"password": {"$eq": "secret"}}}}
    result = _build_success(pipeline, raw, Action.EXPLAIN, policy)
    assert result["status"] == "success"
    assert result["data"] == raw
