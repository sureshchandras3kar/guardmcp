import pytest

from guardmcp.core import metrics
from guardmcp.core.approval.store import ApprovalStore
from guardmcp.core.audit.logger import AuditLogger
from guardmcp.core.pipeline import GuardPipeline
from guardmcp.core.policy.engine import PolicyEngine
from guardmcp.core.risk.engine import RiskEngine


def setup_function():
    metrics.reset()


def test_increment_and_render():
    metrics.increment("guardmcp_requests_total", action="find", status="allowed")
    out = metrics.render_prometheus()
    assert "# TYPE guardmcp_requests_total counter" in out
    assert 'guardmcp_requests_total{action="find",status="allowed"} 1' in out


def test_increment_accumulates_same_labels():
    metrics.increment("guardmcp_requests_total", action="find", status="allowed")
    metrics.increment("guardmcp_requests_total", action="find", status="allowed")
    out = metrics.render_prometheus()
    assert 'guardmcp_requests_total{action="find",status="allowed"} 2' in out


def test_different_labels_tracked_separately():
    metrics.increment("guardmcp_requests_total", action="find", status="allowed")
    metrics.increment("guardmcp_requests_total", action="find", status="denied")
    out = metrics.render_prometheus()
    assert 'status="allowed"} 1' in out
    assert 'status="denied"} 1' in out


def test_empty_registry_renders_empty_string():
    assert metrics.render_prometheus() == ""


def test_label_order_deterministic_regardless_of_call_order():
    metrics.increment("x", b="2", a="1")
    out1 = metrics.render_prometheus()
    metrics.reset()
    metrics.increment("x", a="1", b="2")
    out2 = metrics.render_prometheus()
    assert out1 == out2


# ── Pipeline integration: _audit_event increments the counter ───────────────


class _Loader:
    def __init__(self, policy):
        self._p = policy

    def get(self, agent):
        return self._p


@pytest.mark.asyncio
async def test_audit_event_increments_metrics(tmp_path):
    from guardmcp.core.policy.models import CollectionPolicy, Policy

    policy = Policy(agent="claude", mode="readonly", collections=CollectionPolicy(allow=["*"]))
    pipeline = GuardPipeline(
        policy_loader=_Loader(policy),
        policy_engine=PolicyEngine(),
        risk_engine=RiskEngine(),
        audit_logger=AuditLogger(tmp_path / "audit.jsonl"),
        approval_store=ApprovalStore(timeout_seconds=1.0),
        executor=None,
    )
    await pipeline._audit_event(agent="claude", collection="users", action="find", status="allowed")
    out = metrics.render_prometheus()
    assert 'guardmcp_requests_total{action="find",status="allowed"} 1' in out
