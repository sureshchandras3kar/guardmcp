from guardmcp.core.models.domain import Action, RiskLevel
from guardmcp.core.risk.engine import RiskEngine

engine = RiskEngine()


def test_find_is_low():
    assert engine.classify(Action.FIND) == RiskLevel.LOW


def test_count_is_low():
    assert engine.classify(Action.COUNT) == RiskLevel.LOW


def test_aggregate_is_high():
    assert engine.classify(Action.AGGREGATE) == RiskLevel.HIGH


def test_insert_one_is_medium():
    assert engine.classify(Action.INSERT_ONE) == RiskLevel.MEDIUM


def test_update_one_is_high():
    assert engine.classify(Action.UPDATE_ONE) == RiskLevel.HIGH


def test_update_many_is_high():
    assert engine.classify(Action.UPDATE_MANY) == RiskLevel.HIGH


def test_delete_one_is_high():
    assert engine.classify(Action.DELETE_ONE) == RiskLevel.HIGH


def test_delete_many_is_critical():
    assert engine.classify(Action.DELETE_MANY) == RiskLevel.CRITICAL


def test_drop_is_critical():
    assert engine.classify(Action.DROP) == RiskLevel.CRITICAL


# ── S-4: scope-aware escalation ──────────────────────────────────────────────


def test_update_many_empty_filter_escalates_to_critical():
    assert engine.classify(Action.UPDATE_MANY, {"filter": {}}) == RiskLevel.CRITICAL


def test_update_many_missing_filter_escalates_to_critical():
    assert engine.classify(Action.UPDATE_MANY, {}) == RiskLevel.CRITICAL


def test_update_many_scoped_filter_stays_high():
    assert engine.classify(Action.UPDATE_MANY, {"filter": {"_id": 1}}) == RiskLevel.HIGH


def test_delete_one_empty_filter_escalates_to_critical():
    assert engine.classify(Action.DELETE_ONE, {"filter": {}}) == RiskLevel.CRITICAL


def test_delete_one_scoped_filter_stays_high():
    assert engine.classify(Action.DELETE_ONE, {"filter": {"_id": 1}}) == RiskLevel.HIGH


def test_read_with_empty_filter_unaffected():
    assert engine.classify(Action.FIND, {"filter": {}}) == RiskLevel.LOW


def test_no_params_is_backward_compatible():
    # called without params → static action-type risk
    assert engine.classify(Action.UPDATE_MANY) == RiskLevel.HIGH
