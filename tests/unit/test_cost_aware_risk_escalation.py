"""Opt-in (policy.max_cost) cost->risk live escalation on the authorize path.

Default hot path (max_cost unset) must stay byte-identical to today: no plugin
call, no behavior change. Only agents that set max_cost pay the estimate
round-trip, and only escalated risk that crosses an existing
approval.high/critical flag changes the decision.
"""
from guardmcp.core.interfaces.cost import CostEstimate, CostLevel
from guardmcp.core.models.domain import Action
from guardmcp.core.pipeline import GuardPipeline
from guardmcp.core.policy.engine import PolicyEngine
from guardmcp.core.policy.models import ApprovalPolicy, CollectionPolicy, Policy
from guardmcp.core.risk.engine import RiskEngine


class _Loader:
    def __init__(self, policy):
        self._p = policy

    def get(self, agent):
        return self._p


class _Entry:
    def __init__(self, plugin=None, executor=None):
        self.plugin = plugin
        self.executor = executor


class _Registry:
    def __init__(self, entry):
        self._entry = entry

    def get_active(self):
        return self._entry


class _Plugin:
    def __init__(self, cost: CostLevel):
        self._cost = cost
        self.calls = 0

    async def estimate(self, req):
        self.calls += 1
        return CostEstimate(estimated_cost=self._cost)


class _NoopExecutor:
    async def execute(self, collection, action, params, database=None):
        return {"count": 0}


class _NoopAudit:
    def build(self, **kw):
        return kw

    async def log(self, record):
        return None


class _DenyingApprovalStore:
    """Minimal ApprovalStoreProtocol fake: every approval request times out/denies."""

    def create(self, **kw):
        class _Req:
            approval_id = "test-approval"

        return _Req()

    async def wait_for_decision(self, approval_id):
        return "denied"


def _pipeline(policy, plugin=None):
    entry = _Entry(plugin=plugin, executor=_NoopExecutor())
    return GuardPipeline(
        policy_loader=_Loader(policy),
        policy_engine=PolicyEngine(),
        risk_engine=RiskEngine(),
        audit_logger=_NoopAudit(),
        approval_store=_DenyingApprovalStore(),
        executor=_NoopExecutor(),
        registry=_Registry(entry),
    )


def _policy(max_cost=None, approval_critical=False, mode="readwrite"):
    return Policy(
        agent="claude",
        mode=mode,
        collections=CollectionPolicy(allow=["*"]),
        max_cost=max_cost,
        approval=ApprovalPolicy(critical=approval_critical),
    )


async def test_default_policy_never_calls_plugin_no_max_cost():
    plugin = _Plugin(CostLevel.CRITICAL)
    pipeline = _pipeline(_policy(max_cost=None), plugin=plugin)
    result = await pipeline.run("claude", "users", Action.FIND, {"filter": {}})
    assert result["status"] == "success"
    assert plugin.calls == 0  # opt-out agent: zero extra I/O, unchanged hot path


async def test_cost_at_or_above_max_cost_escalates_risk_and_requires_approval():
    plugin = _Plugin(CostLevel.CRITICAL)
    policy = _policy(max_cost=CostLevel.HIGH, approval_critical=True)
    pipeline = _pipeline(policy, plugin=plugin)
    result = await pipeline.run("claude", "users", Action.FIND, {"filter": {}})
    assert plugin.calls == 1
    assert result["status"] == "denied"  # approval_required + no approval store -> declined
    assert result["code"] == "APPROVAL_DECLINED"


async def test_cost_below_max_cost_does_not_escalate():
    plugin = _Plugin(CostLevel.LOW)
    policy = _policy(max_cost=CostLevel.HIGH, approval_critical=True)
    pipeline = _pipeline(policy, plugin=plugin)
    result = await pipeline.run("claude", "users", Action.FIND, {"filter": {}})
    assert plugin.calls == 1
    assert result["status"] == "success"  # below threshold: no escalation, no approval


async def test_escalation_without_matching_approval_flag_still_allows():
    # max_cost triggers escalation to CRITICAL risk, but approval.critical=False
    # -> decision stays ALLOWED (risk is recorded, behavior unchanged).
    plugin = _Plugin(CostLevel.CRITICAL)
    policy = _policy(max_cost=CostLevel.HIGH, approval_critical=False)
    pipeline = _pipeline(policy, plugin=plugin)
    result = await pipeline.run("claude", "users", Action.FIND, {"filter": {}})
    assert plugin.calls == 1
    assert result["status"] == "success"


async def test_estimation_failure_never_breaks_authorization():
    class _BrokenPlugin:
        async def estimate(self, req):
            raise RuntimeError("backend explain failed")

    policy = _policy(max_cost=CostLevel.HIGH, approval_critical=True)
    pipeline = _pipeline(policy, plugin=_BrokenPlugin())
    result = await pipeline.run("claude", "users", Action.FIND, {"filter": {}})
    assert result["status"] == "success"  # degrades to no escalation, never raises
