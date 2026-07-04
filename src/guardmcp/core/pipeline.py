from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .interfaces.capability import Capability, CapabilityRequest

from .interfaces.backend import Backend
from .interfaces.errors import ErrorCode, TypeMarshalError
from .interfaces.stores import (
    ApprovalStoreProtocol,
    AuditSinkProtocol,
    RateLimiterProtocol,
)
from .models.domain import (
    NO_MASK_ACTIONS,
    Action,
    Decision,
    DecisionStatus,
    Request,
    RiskLevel,
)
from .neutral import neutralize
from .observability import log_event, new_trace_id
from .policy.engine import PolicyEngine
from .policy.loader import PolicyLoader
from .policy.models import Policy
from .policy.trace import PolicyTrace
from .risk.engine import RiskEngine
from .validation import collection_permitted


@dataclass
class EvalResult:
    """Result of policy evaluation before execution."""

    request: Request
    decision: Decision
    policy: Policy | None


class GuardPipeline:
    def __init__(
        self,
        *,
        policy_loader: PolicyLoader,
        policy_engine: PolicyEngine,
        risk_engine: RiskEngine,
        # Risk #4: typed against the governance-state Protocols (not concrete
        # classes) so a distributed Redis/Kafka/QLDB impl drops in unchanged.
        audit_logger: AuditSinkProtocol,
        approval_store: ApprovalStoreProtocol,
        executor: "Backend",
        registry=None,
        limiter: "RateLimiterProtocol | None" = None,
    ) -> None:
        self._policies = policy_loader
        self._policy_engine = policy_engine
        self._risk_engine = risk_engine
        self._audit = audit_logger
        self._approvals = approval_store
        self._executor: Backend = executor
        self._registry = registry
        self._limiter = limiter

    def _audit_params(self, req: Request, policy: Policy | None) -> dict[str, Any]:
        """
        C3: return request params for the audit log with masked-field VALUES
        scrubbed. FieldMasker recurses into filter/update/document/pipeline and
        replaces any masked key's value with the mask sentinel, so the audit
        trail records WHAT was queried without persisting sensitive data.
        """
        if not req.params:
            return {}
        if policy is None or not policy.mask_fields_for(req.collection, req.database):
            return req.params
        # M1: cached, collection- AND database-aware masker
        return policy.audit_masker(req.collection, req.database).mask_result(req.params)

    async def _audit_event(
        self,
        *,
        agent: str,
        collection: str,
        action: str,
        status: str,
        reason: str | None = None,
        risk: "RiskLevel | None" = None,
        request_id: str | None = None,
        params: dict[str, Any] | None = None,
        database: str | None = None,
    ) -> None:
        """Build + emit a single audit record.

        Centralizes the build+log pair and the ``risk.value if risk else None``
        normalization so every call site stays byte-identical. The HMAC audit
        chain is order-sensitive — this helper does NOT reorder or batch; callers
        must invoke it in the SAME sequence as the records were emitted before.
        """
        await self._audit.log(
            self._audit.build(
                agent=agent,
                collection=collection,
                action=action,
                status=status,
                reason=reason,
                risk=risk.value if risk else None,
                request_id=request_id,
                params=params,
                database=database,
            )
        )

    def _get_executor(self) -> "Backend":
        """Return executor for the active connection (or default)."""
        if self._registry:
            entry = self._registry.get_active()
            if entry is not None and getattr(entry, "executor", None) is not None:
                return entry.executor
        return self._executor

    # ── Policy evaluation (no execution) ──────────────────────────────────────

    def evaluate(
        self,
        agent: str,
        collection: str,
        action: Action,
        params: dict[str, Any],
        trace: "PolicyTrace | None" = None,
        policy_override: Policy | None = None,
        database: str | None = None,
    ) -> EvalResult:
        """Run policy + risk check. Does NOT execute or audit.

        `trace` (optional): when supplied, every rule check appends a TraceStep
        at its existing decision point — the SINGLE-SOURCE-OF-TRUTH mechanism
        powering guardmcp_explain_policy. When None (the default / hot path) no
        appends happen and behavior + perf are identical to an untraced run.

        `policy_override` (optional): evaluate against THIS policy instead of the
        loader's policy for `agent`. Used by guardmcp_simulate_policy to run the
        SAME evaluation against a hypothetical policy without touching the loader.
        When None (the default) the loader lookup is used exactly as before.

        `database` (optional): the target database name for multi-database
        governance. When None (default), single-DB back-compat path is used.
        """
        request = Request(agent=agent, collection=collection, action=action, params=params,
                          database=database)
        policy = policy_override if policy_override is not None else self._policies.get(agent)

        if policy is None:
            if trace is not None:
                trace.add(
                    "policy",
                    "policy_lookup",
                    "matched",
                    f"no policy configured for agent '{agent}'",
                )
            return EvalResult(
                request=request,
                decision=Decision(
                    status=DecisionStatus.DENIED,
                    reason=f"no policy configured for agent '{agent}'",
                    code=ErrorCode.POLICY_DENIED.value,
                ),
                policy=None,
            )

        # Temporal validity: a scheduled/temporary policy only applies inside
        # its [not_before, not_after] window. Outside it, deny.
        temporal = self._check_temporal(agent, policy)
        if temporal is not None:
            if trace is not None:
                trace.add(
                    "pipeline",
                    "temporal_window",
                    "matched",
                    "policy not active at this time",
                )
            return EvalResult(request=request, decision=temporal, policy=policy)
        if trace is not None and (policy.not_before is not None or policy.not_after is not None):
            trace.add("pipeline", "temporal_window", "passed", "within active window")

        # Database gate: deny if the policy does not permit the requested database.
        if not policy.database_permitted(database):
            if trace is not None:
                trace.add("policy", "database_access", "matched",
                          f"database '{database}' not permitted by policy")
            return EvalResult(
                request=request,
                decision=Decision(
                    status=DecisionStatus.DENIED,
                    reason=f"database '{database}' is not permitted by policy.",
                    code=ErrorCode.DATABASE_NOT_ALLOWED.value,
                ),
                policy=policy,
            )

        # C1 + C2: aggregation pipelines can reach other collections ($lookup)
        # and leak masked values via field aliasing ($group/$project). Enforce
        # before the normal decision so a permitted action can still be denied
        # for what its pipeline references.
        pipeline_guard = self._guard_aggregation(request, policy)
        if pipeline_guard is not None:
            if trace is not None:
                trace.add(
                    "pipeline",
                    "aggregation_guard",
                    "matched",
                    "pipeline references a forbidden collection or masked field",
                )
            return EvalResult(request=request, decision=pipeline_guard, policy=policy)
        if trace is not None and request.params.get("pipeline"):
            trace.add("pipeline", "aggregation_guard", "passed", "pipeline references permitted")

        risk = self._risk_engine.classify(action, params)
        decision = self._policy_engine.evaluate(
            request, policy, risk, trace=trace, database=database
        )
        return EvalResult(request=request, decision=decision, policy=policy)

    def evaluate_capability(
        self,
        agent: str,
        resource: str,
        capability: "Capability",
        request: "CapabilityRequest | None" = None,
    ) -> EvalResult:
        """#1 seam: capability-native entry point.

        Maps a Capability → a representative legacy Action and delegates to
        evaluate(). The concrete Action is taken from request.action when the
        caller pinned one (authoritative for the ambiguous write caps), else from
        CAPABILITY_TO_ACTION. This gives a capability-first surface WITHOUT
        deleting Action; v2 will invert the primacy (Capability becomes the
        canonical axis and Action becomes the derived/compat view).
        """
        from .interfaces.capability import CAPABILITY_TO_ACTION

        action_value = None
        params: dict[str, Any] = {}
        if request is not None:
            if request.action is not None:
                action_value = (
                    request.action.value if isinstance(request.action, Action) else request.action
                )
            params = request.model_dump(exclude_none=True)
        if action_value is None:
            action_value = CAPABILITY_TO_ACTION.get(capability)
        if action_value is None:
            return EvalResult(
                request=Request(
                    agent=agent,
                    collection=resource,
                    action=Action.FIND,
                    params=params,
                ),
                decision=Decision(
                    status=DecisionStatus.DENIED,
                    reason=f"capability '{capability}' has no representative action",
                    code=ErrorCode.UNSUPPORTED_CAPABILITY.value,
                ),
                policy=None,
            )
        return self.evaluate(agent, resource, Action(action_value), params)

    def _check_temporal(self, agent: str, policy: Policy) -> Decision | None:
        """Deny if the policy has a temporal window and now is outside it."""
        if policy.not_before is None and policy.not_after is None:
            return None
        now = datetime.now(UTC)

        def _aware(dt: datetime) -> datetime:
            # Treat naive datetimes (from ISO strings without tz) as UTC.
            return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)

        nb = _aware(policy.not_before) if policy.not_before else None
        na = _aware(policy.not_after) if policy.not_after else None
        if (nb is not None and now < nb) or (na is not None and now > na):
            window = (
                f"{policy.not_before.isoformat() if policy.not_before else '-inf'}.."
                f"{policy.not_after.isoformat() if policy.not_after else '+inf'}"
            )
            return Decision(
                status=DecisionStatus.DENIED,
                reason=(
                    f"policy for agent '{agent}' is not active at this time (window: {window})"
                ),
                code=ErrorCode.POLICY_DENIED.value,
            )
        return None

    def _guard_aggregation(self, request: Request, policy: Policy) -> Decision | None:
        """
        C1/C2 guard for aggregation pipelines. Returns a DENIED Decision if the
        pipeline references a forbidden collection or a masked field path;
        otherwise None (no objection).
        """
        # Applies to aggregate, and explain in aggregate mode.
        stages = request.params.get("pipeline")
        if not stages:
            return None

        # Pipeline introspection is backend-specific knowledge owned by the
        # plugin/executor. Go through the active executor's capability methods.
        # A backend without aggregation exposes no such methods → no refs to guard.
        executor = self._get_executor()
        ref_collections = getattr(executor, "referenced_collections", None)
        masked_refs = getattr(executor, "masked_field_references", None)

        # Resolve against the PER-DATABASE scope so an aggregation in DB-A is
        # judged by DB-A's collection allow/deny and masked fields — not the flat
        # policy, which could permit a collection or unmask a field governed
        # differently in another database.
        scope = policy.scope_for(request.database)

        # C1: every foreign collection ($lookup.from, $graphLookup.from,
        # $unionWith, nested sub-pipelines) must pass the collection policy.
        if ref_collections is not None:
            for ref in ref_collections(request.params):
                if not collection_permitted(ref, scope.collections.allow, scope.collections.deny):
                    return Decision(
                        status=DecisionStatus.DENIED,
                        reason=(
                            f"aggregation references collection '{ref}' which is not "
                            f"permitted by policy (via $lookup/$graphLookup/$unionWith)."
                        ),
                        code=ErrorCode.COLLECTION_NOT_ALLOWED.value,
                    )

        # C2: masking is by key name and is NOT rename-safe. If the pipeline
        # references a masked field path, the masked VALUE could surface under a
        # different key — deny rather than leak.
        leaked = (
            masked_refs(
                request.params,
                policy.mask_fields_for(request.collection, request.database),
            )
            if masked_refs is not None
            else set()
        )
        if leaked:
            return Decision(
                status=DecisionStatus.DENIED,
                reason=(
                    f"aggregation references masked field(s) {sorted(leaked)}. "
                    "Masking cannot be guaranteed once a field is grouped, projected, "
                    "or renamed — remove the reference or unmask the field in policy."
                ),
                code=ErrorCode.POLICY_DENIED.value,
            )
        return None

    # ── Execute after in-band confirmation ────────────────────────────────────

    async def execute_approved(self, eval_result: EvalResult) -> dict[str, Any]:
        """
        Execute after human confirmed in-band via ctx.elicit().

        Re-evaluates policy to close the TOCTOU window: policy may have changed
        during the elicit wait (up to 300s). If it now denies, we reject.
        """
        req = eval_result.request
        # #8: one trace id per executed request, shared by logs + audit record.
        new_trace_id()

        # TOCTOU fix: re-check policy now, not the cached eval from before elicit.
        # Preserve the target database so the re-check + masking stay db-aware.
        fresh = self.evaluate(
            req.agent, req.collection, req.action, req.params, database=req.database
        )
        if fresh.decision.status == DecisionStatus.DENIED:
            await self._audit_event(
                agent=req.agent,
                collection=req.collection,
                action=req.action.value,
                status="denied",
                reason=f"policy changed during approval wait: {fresh.decision.reason}",
                request_id=req.request_id,
                params=self._audit_params(req, fresh.policy),
            )
            return {
                "status": "denied",
                "reason": fresh.decision.reason,
                "code": fresh.decision.code,
            }

        await self._audit_event(
            agent=req.agent,
            collection=req.collection,
            action=req.action.value,
            status="approved",
            reason="approved by user",
            risk=fresh.decision.risk,
            request_id=req.request_id,
            params=self._audit_params(req, fresh.policy),
        )

        return await self._execute_and_build(req, fresh.policy, database=req.database)

    # ── Full pipeline (REST approval mode) ────────────────────────────────────

    async def run(
        self,
        agent: str,
        collection: str,
        action: Action,
        params: dict[str, Any],
        incoming_traceparent: str | None = None,
        database: str | None = None,
    ) -> dict[str, Any]:
        """Full pipeline: evaluate → approve (REST API) → execute → mask.

        #9 seam: an inbound W3C `traceparent` (from an MCP/HTTP header) may be
        passed to CONTINUE the caller's distributed trace. Wiring the transport
        header into this param is transport-specific; default None mints a fresh
        trace-id as before.

        `database` (optional): the target database name for multi-database
        governance. When None (default), single-DB back-compat path is used.
        """
        # #8/#9: one trace id per request, shared by structured logs + audit
        # record; continues an inbound traceparent when supplied.
        new_trace_id(incoming_traceparent)
        if self._limiter and not await self._limiter.check(agent):
            return {
                "status": "error",
                "reason": f"rate limit exceeded for agent '{agent}'. Try again shortly.",
                "code": ErrorCode.RATE_LIMITED.value,
            }

        eval_result = self.evaluate(agent, collection, action, params, database=database)
        req = eval_result.request
        decision = eval_result.decision
        policy = eval_result.policy

        await self._audit_event(
            agent=agent,
            collection=collection,
            action=action.value,
            status=decision.status.value,
            reason=decision.reason,
            risk=decision.risk,
            request_id=req.request_id,
            params=self._audit_params(req, policy),
        )

        if decision.status == DecisionStatus.DENIED:
            return {"status": "denied", "reason": decision.reason, "code": decision.code}

        if decision.status == DecisionStatus.APPROVAL_REQUIRED:
            approval_req = self._approvals.create(
                agent=agent,
                action=action.value,
                collection=collection,
                risk=decision.risk or RiskLevel.HIGH,
                reason=decision.reason,
                params=params,
            )
            outcome = await self._approvals.wait_for_decision(approval_req.approval_id)
            final = "approved" if outcome == "approved" else "denied"
            await self._audit_event(
                agent=agent,
                collection=collection,
                action=action.value,
                status=final,
                reason="human approved"
                if outcome == "approved"
                else "approval denied or timed out",
                risk=decision.risk,
                request_id=req.request_id,
                params=self._audit_params(req, policy),
            )
            if outcome != "approved":
                return {
                    "status": "denied",
                    "reason": "approval denied or timed out.",
                    "code": ErrorCode.APPROVAL_DECLINED.value,
                }

        return await self._execute_and_build(req, policy, database=req.database)

    # ── Shared execution helper ───────────────────────────────────────────────

    async def _execute_and_build(
        self, req: Request, policy: Policy | None, database: str | None = None
    ) -> dict[str, Any]:
        """Execute request and build masked success response."""
        executor = self._get_executor()
        params = req.params
        # Inject policy mask_fields for schema inference (collection-aware)
        if req.action == Action.COLLECTION_SCHEMA and policy is not None:
            params = {**params, "mask_fields": policy.mask_fields_for(req.collection, req.database)}
        try:
            raw = await executor.execute(req.collection, req.action, params, database=database)
        except TypeMarshalError as exc:
            # A typed filter value could not be coerced to the field's known
            # BSON type (the marshalling layer raised). Surface a LOUD,
            # actionable TYPE_MISMATCH instead of a generic backend error or —
            # worse — a silently empty result. The message from the marshaller
            # already names the field, expected type, and escape hatch, so it is
            # safe and useful to pass through verbatim.
            msg = str(exc)
            log_event(
                "warning",
                "type_mismatch",
                detail=msg,
                collection=req.collection,
                action=req.action.value,
            )
            await self._audit_event(
                agent=req.agent,
                collection=req.collection,
                action=req.action.value,
                status="error",
                reason=msg,
                request_id=req.request_id,
                params=self._audit_params(req, policy),
            )
            return {
                "status": "error",
                "reason": msg,
                "code": ErrorCode.TYPE_MISMATCH.value,
            }
        except Exception as exc:
            log_event(
                "error",
                "executor_error",
                detail=repr(exc),
                collection=req.collection,
                action=req.action.value,
            )
            # Error sanitization is backend-specific — delegate to the executor
            # when it provides it, keeping core database-agnostic.
            sanitize = getattr(executor, "sanitize_error", None)
            safe_msg = (
                sanitize(exc) if sanitize else "Operation failed. Check parameters and try again."
            )
            await self._audit_event(
                agent=req.agent,
                collection=req.collection,
                action=req.action.value,
                status="error",
                reason=safe_msg,
                request_id=req.request_id,
                params=self._audit_params(req, policy),
            )
            return {"status": "error", "reason": safe_msg, "code": ErrorCode.BACKEND_ERROR.value}

        return self._build_success(raw, req.action, policy, req.collection, req.database)

    # ── Discovery ─────────────────────────────────────────────────────────────

    async def discover_collections(
        self, agent: str, database: str | None = None
    ) -> list[str]:
        """Return only collections the agent's policy permits."""
        policy = self._policies.get(agent)
        # CR-2: discovery was previously unaudited — a collection-enumeration
        # probe left no trace. Log every call.
        await self._audit_event(
            agent=agent,
            collection="*",
            action="list_collections",
            status="allowed" if policy is not None else "denied",
            reason=None if policy is not None else f"no policy for agent '{agent}'",
            database=database,
        )
        if policy is None:
            return []
        executor = self._get_executor()
        all_cols = await executor.list_collections(database)
        if database is not None:
            scope = policy.scope_for(database)
            return [
                c
                for c in all_cols
                if collection_permitted(c, scope.collections.allow, scope.collections.deny)
            ]
        return [
            c
            for c in all_cols
            if collection_permitted(c, policy.collections.allow, policy.collections.deny)
        ]

    async def describe_collection(
        self, agent: str, collection: str, database: str | None = None
    ) -> dict[str, Any] | None:
        """Field schema with masked fields hidden."""
        policy = self._policies.get(agent)
        scope = policy.scope_for(database) if policy is not None else None
        permitted = policy is not None and collection_permitted(
            collection, scope.collections.allow, scope.collections.deny
        )
        # CR-2: schema inference samples real documents — audit it.
        await self._audit_event(
            agent=agent,
            collection=collection,
            action="collection_schema",
            status="allowed" if permitted else "denied",
            database=database,
        )
        if policy is None:
            return None
        if not permitted:
            return None
        executor = self._get_executor()
        schema = await executor.collection_schema(
            collection, policy.mask_fields_for(collection, database), database=database
        )
        if not schema:
            return {"fields": {}, "note": "collection is empty"}
        return {"fields": schema}

    async def use_database_audited(self, agent: str, name: str) -> bool:
        policy = self._policies.get(agent)
        permitted = policy is not None and policy.database_permitted(name)
        await self._audit_event(
            agent=agent, collection="*", action="use_database",
            status="allowed" if permitted else "denied",
            reason=None if permitted else f"database '{name}' not permitted by policy",
            database=name,
        )
        return permitted

    async def switch_connection_audited(self, agent: str, name: str) -> bool:
        """
        CR-2: switching the active connection is a security-relevant control
        action (it changes which database the agent reads). Audit it, then
        perform the switch.

        S-6: gate the switch by policy. If the agent's policy declares a
        non-empty connections_allow list and `name` is not in it, deny the
        switch (and audit the denial) without touching the active connection.
        """
        policy = self._policies.get(agent)
        if policy is not None and policy.connections_allow and name not in policy.connections_allow:
            await self._audit_event(
                agent=agent,
                collection="*",
                action="switch_connection",
                status="denied",
                reason=f"connection '{name}' not permitted by policy",
            )
            return False
        ok = self.switch_connection(name)
        await self._audit_event(
            agent=agent,
            collection="*",
            action="switch_connection",
            status="allowed" if ok else "denied",
            reason=f"connection '{name}'" if ok else f"unknown connection '{name}'",
        )
        return ok

    # ── Connection management ──────────────────────────────────────────────────

    def switch_connection(self, name: str) -> bool:
        if self._registry is None:
            return False
        return self._registry.switch(name)

    def list_connections(self) -> list[str]:
        if self._registry is None:
            return ["default"]
        return self._registry.list_names()

    def active_connection(self) -> str:
        if self._registry is None:
            return "default"
        return self._registry.active_name()

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _build_success(
        self,
        raw: Any,
        action: Action,
        policy: Policy | None,
        collection: str = "*",
        database: str | None = None,
    ) -> dict[str, Any]:
        if policy is None:
            data = raw
            return self._with_neutral({"status": "success", "data": data}, action, data)

        # S-1: explain plans are not documents, but MongoDB echoes filter
        # literals + index bounds into the plan. Run the plan through the masker
        # so any nested key matching a masked field is redacted in the output.
        if action == Action.EXPLAIN:
            masked_plan = policy.audit_masker(collection, database).mask_result(raw)  # M1
            return self._with_neutral(
                {"status": "success", "data": masked_plan}, action, masked_plan
            )

        if action in NO_MASK_ACTIONS:
            return self._with_neutral({"status": "success", "data": raw}, action, raw)

        # H3/M1: single-pass field-allow + mask via the policy-cached transformer.
        transform = policy.result_transformer(collection, database).transform_result

        # find returns {documents: [...], ...} — transform only the documents list
        if isinstance(raw, dict) and "documents" in raw:
            data = {**raw, "documents": transform(raw["documents"])}
            return self._with_neutral({"status": "success", "data": data}, action, data)
        data = transform(raw)
        return self._with_neutral({"status": "success", "data": data}, action, data)

    @staticmethod
    def _with_neutral(envelope: dict[str, Any], action: Action, data: Any) -> dict[str, Any]:
        """
        #6: attach backend-neutral accessors (rows/affected/scalar) alongside the
        native `data` so a consumer reads result["neutral"]["rows"] uniformly for
        ANY backend. ADDITIVE — `data` keeps its native (Mongo or SQL) shape, the
        neutral view is computed from the MASKED data so it never leaks values.
        """
        envelope["neutral"] = neutralize(action, data)
        return envelope
