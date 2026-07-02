from guardmcp.core.interfaces.capability import Capability, CapabilityRequest
from guardmcp.core.interfaces.cost import CostEstimate, CostLevel
from guardmcp.core.planning.models import AlternativePlan, ExecutionPlan
from guardmcp.core.planning.recommend import RecommendationEngine


def _plan(strategy, index_used, cost, decision="allowed"):
    return ExecutionPlan(
        strategy=strategy,
        request=CapabilityRequest(capability=Capability.READ, resource="user"),
        index_used=index_used,
        est_cost=CostEstimate(estimated_cost=cost),
        governance={"decision": decision},
    )


def test_index_plan_ranked_above_scan():
    scan = _plan("collection_scan", False, CostLevel.HIGH)
    idx = _plan("index_scan", True, CostLevel.LOW)
    ranked = RecommendationEngine().rank([scan, idx])
    assert ranked[0].strategy == "index_scan"
    assert ranked[0].rank == 1
    assert ranked[1].rank == 2


def test_denied_plan_ranked_last():
    ok = _plan("collection_scan", False, CostLevel.HIGH, decision="allowed")
    denied = _plan("index_scan", True, CostLevel.LOW, decision="denied")
    ranked = RecommendationEngine().rank([denied, ok])
    assert ranked[0].strategy == "collection_scan"


def test_tradeoff_filled_when_empty():
    ranked = RecommendationEngine().rank([_plan("index_scan", True, CostLevel.LOW)])
    assert "index" in ranked[0].tradeoff.lower()


def test_stable_for_equal_scores():
    a = _plan("index_scan", True, CostLevel.LOW)
    b = _plan("index_scan", True, CostLevel.LOW)
    ranked = RecommendationEngine().rank([a, b])
    assert [p.rank for p in ranked] == [1, 2]


def test_approval_required_penalized_between_allowed_and_denied():
    """Test that approval_required ranks between allowed and denied by decision."""
    allowed = _plan("index_scan", True, CostLevel.LOW, decision="allowed")
    approval_req = _plan("index_scan", True, CostLevel.LOW, decision="approval_required")
    denied = _plan("index_scan", True, CostLevel.LOW, decision="denied")

    ranked = RecommendationEngine().rank([denied, approval_req, allowed])

    # Order should be: allowed (rank 1), approval_required (rank 2), denied (rank 3)
    assert ranked[0].governance["decision"] == "allowed"
    assert ranked[0].rank == 1
    assert ranked[1].governance["decision"] == "approval_required"
    assert ranked[1].rank == 2
    assert ranked[2].governance["decision"] == "denied"
    assert ranked[2].rank == 3


def test_est_cost_none_defaults_to_unknown_rank():
    """Test that est_cost=None defaults to UNKNOWN cost rank (2), which ranks below MEDIUM (1)."""
    # Plan with UNKNOWN cost (est_cost=None)
    unknown = ExecutionPlan(
        strategy="index_scan",
        request=CapabilityRequest(capability=Capability.READ, resource="user"),
        index_used=True,
        est_cost=None,
        governance={"decision": "allowed"},
    )
    # Plan with MEDIUM cost
    medium = _plan("index_scan", True, CostLevel.MEDIUM, decision="allowed")

    ranked = RecommendationEngine().rank([unknown, medium])

    # MEDIUM (cost_rank=1) should rank before UNKNOWN (cost_rank=2)
    assert ranked[0].est_cost is not None
    assert ranked[0].est_cost.estimated_cost == CostLevel.MEDIUM
    assert ranked[0].rank == 1
    assert ranked[1].est_cost is None
    assert ranked[1].rank == 2


def test_reranking_already_ranked_alternativeplan_is_idempotent_shape():
    """Test that rank() on AlternativePlans (already ranked) is idempotent in structure."""
    plans = [
        _plan("index_scan", True, CostLevel.LOW),
        _plan("collection_scan", False, CostLevel.HIGH),
    ]

    # First ranking
    ranked1 = RecommendationEngine().rank(plans)
    assert len(ranked1) == 2
    assert [p.rank for p in ranked1] == [1, 2]
    original_tradeoff = ranked1[0].tradeoff
    assert original_tradeoff  # Must be non-empty

    # Re-rank the already-ranked AlternativePlans
    ranked2 = RecommendationEngine().rank(ranked1)

    # Should not raise and produce contiguous ranks
    assert len(ranked2) == 2
    assert [p.rank for p in ranked2] == [1, 2]
    # Tradeoff should be preserved from first pass
    assert ranked2[0].tradeoff == original_tradeoff


def test_existing_tradeoff_preserved():
    """Test that an explicitly set tradeoff is preserved and not overwritten by rank()."""
    custom_tradeoff = "custom note: hand-tuned for analytics workload"
    plan = AlternativePlan(
        strategy="index_scan",
        request=CapabilityRequest(capability=Capability.READ, resource="user"),
        index_used=True,
        est_cost=CostEstimate(estimated_cost=CostLevel.LOW),
        governance={"decision": "allowed"},
        rank=0,
        tradeoff=custom_tradeoff,
    )

    ranked = RecommendationEngine().rank([plan])

    # The custom tradeoff should be preserved
    assert ranked[0].tradeoff == custom_tradeoff
