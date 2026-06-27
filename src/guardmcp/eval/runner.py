"""
Eval runner: builds an isolated GuardPipeline per eval case and runs it.

Uses mongomock-motor for MongoDB — no real database required.
"""

import tempfile
import time
from pathlib import Path
from typing import Any

from mongomock_motor import AsyncMongoMockClient

from ..core.approval.store import ApprovalStore
from ..core.audit.logger import AuditLogger
from ..core.models.domain import Action, DecisionStatus
from ..core.pipeline import GuardPipeline
from ..core.policy.engine import PolicyEngine
from ..core.policy.models import ActionPolicy, ApprovalPolicy, CollectionPolicy, Policy
from ..core.risk.engine import RiskEngine
from ..plugins.mongodb.executor import MongoExecutor
from .assertions.engine import AssertionEngine
from .fixture import seed
from .models import EvalCase, EvalCaseResult, InlinePolicy

# ── Approval store that never blocks ─────────────────────────────────────────


class _EvalApprovalStore(ApprovalStore):
    """Approval store for evals. Records whether approval was requested; never blocks."""

    def __init__(self, auto_approve: bool = False) -> None:
        super().__init__(timeout_seconds=0.001)
        self.approval_was_requested = False
        self._auto = auto_approve

    async def wait_for_decision(self, approval_id: str) -> str:
        self.approval_was_requested = True
        if self._auto:
            self.resolve(approval_id, approved=True)
            return "approved"
        req = self._store.get(approval_id)
        if req:
            req.status = "denied"
        return "denied"


# ── Inline policy loader ──────────────────────────────────────────────────────


class _InlineLoader:
    """PolicyLoader backed by an in-memory Policy — no YAML file needed."""

    def __init__(self, policy: Policy) -> None:
        self._policy = policy

    def get(self, agent: str) -> Policy | None:
        return self._policy if agent == self._policy.agent else None

    def all(self) -> list[Policy]:
        return [self._policy]

    def load(self) -> None:
        pass

    def start_hot_reload(self) -> None:
        pass

    def stop_hot_reload(self) -> None:
        pass


# ── Policy builder ────────────────────────────────────────────────────────────


def _build_policy(inline: InlinePolicy) -> Policy:
    col = inline.collections
    act = inline.actions
    appr = inline.approval
    return Policy(
        agent=inline.agent,
        mode=inline.mode,
        collections=CollectionPolicy(
            allow=col.get("allow", []),
            deny=col.get("deny", []),
        ),
        actions=ActionPolicy(
            allow=act.get("allow", []),
            deny=act.get("deny", []),
        ),
        mask_fields=inline.mask_fields,
        fields_allow=inline.fields_allow,
        connections_allow=inline.connections_allow,
        approval=ApprovalPolicy(
            high=appr.get("high", False),
            critical=appr.get("critical", False),
        ),
    )


# ── Mock MongoDB client ───────────────────────────────────────────────────────


def _build_mock_client(mongo_client: AsyncMongoMockClient, db_name: str = "evaldb"):
    class _Client:
        def get_collection(self, name):
            return mongo_client[db_name][name]

        def get_db(self):
            return mongo_client[db_name]

        async def list_collection_names(self):
            return await mongo_client[db_name].list_collection_names()

        async def list_databases(self):
            return [{"name": db_name, "sizeOnDisk": 0}]

        def close(self):
            pass

    return _Client()


# ── Case runner ───────────────────────────────────────────────────────────────


async def run_case(case: EvalCase) -> EvalCaseResult:
    """Run one eval case in full isolation. Returns EvalCaseResult."""
    start = time.monotonic()

    if case.skip:
        return EvalCaseResult(
            case_name=case.name,
            passed=True,
            skipped=True,
            skip_reason=case.skip_reason,
            tags=case.tags,
        )

    # Resolve action
    try:
        action = Action(case.request.action)
    except ValueError:
        return EvalCaseResult(
            case_name=case.name,
            passed=False,
            failures=[f"unknown action: '{case.request.action}'"],
            duration_ms=(time.monotonic() - start) * 1000,
            tags=case.tags,
        )

    # Build isolated pipeline
    mongo_client: Any = AsyncMongoMockClient()
    await seed(mongo_client, case.fixtures)
    client = _build_mock_client(mongo_client)

    executor = MongoExecutor(client, schema_cache_ttl=0)
    loader = _InlineLoader(_build_policy(case.policy))
    auto_approve = case.expected.simulate_approval == "approve"
    approval_store = _EvalApprovalStore(auto_approve=auto_approve)

    tmp = Path(tempfile.mkdtemp())
    audit = AuditLogger(tmp / "audit.jsonl")

    pipeline = GuardPipeline(
        # _InlineLoader is a structural stand-in for the concrete PolicyLoader.
        policy_loader=loader,  # type: ignore[arg-type]
        policy_engine=PolicyEngine(),
        risk_engine=RiskEngine(),
        audit_logger=audit,
        approval_store=approval_store,
        executor=executor,
    )

    agent = case.request.agent
    collection = case.request.collection
    params = case.request.params

    # Phase 1: policy evaluation (always — no side effects)
    eval_result = pipeline.evaluate(agent, collection, action, params)
    decision_status = eval_result.decision.status.value  # allowed | denied | approval_required

    # Phase 2: execution (skip for approval_required unless simulating approval)
    actual: dict[str, Any] | None = None
    needs_execution = (
        case.expected.status is not None
        or case.expected.masked_fields
        or case.expected.unmasked_fields
        or case.expected.data_count is not None
        or case.expected.data_contains
        or case.expected.error_contains is not None
        or case.expected.reason_contains is not None
        or case.expected.reason_matches is not None
    )

    if needs_execution and (
        decision_status != DecisionStatus.APPROVAL_REQUIRED.value or auto_approve
    ):
        actual = await pipeline.run(agent, collection, action, params)

    # Phase 3: assertions
    engine = AssertionEngine()
    failures = engine.check(actual or {}, case.expected, decision_status)

    return EvalCaseResult(
        case_name=case.name,
        passed=len(failures) == 0,
        failures=failures,
        actual=actual,
        decision_status=decision_status,
        duration_ms=(time.monotonic() - start) * 1000,
        tags=case.tags,
    )
