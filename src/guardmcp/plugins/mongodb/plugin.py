"""
Formal MongoDB DatabasePlugin.

Owns MongoDB-specific guard knowledge (aggregation cross-resource refs, banned
stages/operators) and exposes it through the generic plugin contract. In P3 the
plugin is the formal contract + guard owner; execution still flows through
MongoExecutor.execute as before (the pipeline is NOT rewired through
plugin.execute yet — that is a later phase).
"""

from __future__ import annotations

from mcp.server.fastmcp.exceptions import ToolError

from ...core.interfaces.capability import (
    CAPABILITY_TO_ACTION,
    Capability,
    CapabilityRequest,
    CapabilityResult,
)
from ...core.interfaces.cost import CostEstimate, CostLevel
from ...core.interfaces.errors import GuardExecutionError, GuardValidationError
from ...core.interfaces.plugin import DatabasePlugin
from ...core.models.domain import Action
from .client import MongoClient
from .cost import normalize_mongo_explain
from .executor import MongoExecutor
from .guard import (
    extract_pipeline_collections,
    validate_filter,
    validate_pipeline_stages,
)

# Reverse mapping for resolving a capability to a default Action when the caller
# does not pin an explicit operation via req.action. WRITE_ONE / WRITE_MANY are
# ambiguous (insert vs update) — default to insert; callers set req.action to
# disambiguate. Built from the core CAPABILITY_TO_ACTION (str values) so the two
# stay in lock-step; we re-hydrate the Action enum the executor expects.
_CAPABILITY_TO_ACTION: dict[Capability, Action] = {
    cap: Action(value) for cap, value in CAPABILITY_TO_ACTION.items()
}


class MongoPlugin(DatabasePlugin):
    name = "mongodb"
    api_version = "1.0"
    supported: frozenset[Capability] = frozenset(Capability)
    # #7: static dialect features — readable from the class manifest WITHOUT
    # instantiating the plugin or connecting.
    dialect_features = {
        "model": "document",
        "supports_aggregation": True,
        "supports_returning": False,
        "supports_cost_estimate": True,  # via explain(executionStats)
    }

    def __init__(
        self,
        executor: MongoExecutor | None = None,
        client: MongoClient | None = None,
    ) -> None:
        self._executor = executor
        self._client = client

    # ── Lifecycle ───────────────────────────────────────────────────────────
    async def connect(self, dsn: str, options: dict) -> None:
        # Connection is owned by ConnectionRegistry / MongoClient in P3; the
        # plugin wraps an already-built executor+client. No-op here.
        return None

    async def health(self) -> bool:
        if self._client is None:
            return False
        ping = getattr(self._client, "ping", None)
        if ping is None:
            return False
        try:
            return bool(await ping())
        except Exception:
            return False

    async def close(self) -> None:
        if self._client is not None:
            self._client.close()

    # ── Execution (NOT on the pipeline hot path in P3) ───────────────────────
    async def execute(self, req: CapabilityRequest) -> CapabilityResult:
        if self._executor is None:
            raise GuardExecutionError("MongoPlugin has no executor bound")
        action = self._resolve_action(req)
        params = self._params_from_request(req)
        raw = await self._executor.execute(req.resource, action, params)
        return self._to_result(raw)

    def _resolve_action(self, req: CapabilityRequest) -> Action:
        # req.action is authoritative when set (Risk #1): it pins the concrete
        # operation (e.g. update_one vs insert_one) without smuggling through
        # options. Falls back to the unambiguous-by-default capability map.
        if req.action is not None:
            return req.action if isinstance(req.action, Action) else Action(req.action)
        return _CAPABILITY_TO_ACTION[req.capability]

    @staticmethod
    def _params_from_request(req: CapabilityRequest) -> dict:
        params: dict = {}
        if req.filter is not None:
            params["filter"] = req.filter
        if req.projection is not None:
            params["projection"] = req.projection
        if req.documents is not None:
            params["documents"] = req.documents
        if req.update is not None:
            params["update"] = req.update
        if req.pipeline is not None:
            params["pipeline"] = req.pipeline
        if req.limit is not None:
            params["limit"] = req.limit
        if req.skip is not None:
            params["skip"] = req.skip
        if req.sort is not None:
            params["sort"] = req.sort
        # carry through any extra backend params from options (no control keys
        # are smuggled here anymore — the concrete op lives in req.action).
        for k, v in req.options.items():
            params.setdefault(k, v)
        return params

    @staticmethod
    def _to_result(raw) -> CapabilityResult:
        if isinstance(raw, dict) and "documents" in raw:
            meta = {k: v for k, v in raw.items() if k != "documents"}
            return CapabilityResult(rows=raw["documents"], meta=meta)
        if isinstance(raw, list):
            return CapabilityResult(rows=raw)
        if isinstance(raw, int):
            return CapabilityResult(scalar=raw)
        if isinstance(raw, dict):
            return CapabilityResult(meta=raw)
        return CapabilityResult(meta={"data": raw})

    # ── Validation / guard ownership ─────────────────────────────────────────
    def validate_request(self, req: CapabilityRequest) -> None:
        """Backend safety validation. Re-raises tool-layer ToolError as
        GuardValidationError so callers reason in core error terms."""
        try:
            if req.capability == Capability.AGGREGATE and req.pipeline is not None:
                validate_pipeline_stages(req.pipeline)
            if req.filter is not None:
                validate_filter(req.filter)
        except ToolError as exc:
            raise GuardValidationError(str(exc)) from exc

    def cross_resource_refs(self, req: CapabilityRequest) -> set[str]:
        return extract_pipeline_collections(req.pipeline or [])

    # ── Cost estimation ──────────────────────────────────────────────────────
    async def estimate(self, req: CapabilityRequest) -> CostEstimate:
        """Estimate the cost of a find/aggregate via explain(executionStats),
        normalized to a CostEstimate. NEVER returns the raw plan. Best-effort:
        unsupported ops or explain failures return UNKNOWN + a warning rather
        than raising — callers (guardmcp_plan) must never crash on estimation."""
        if self._executor is None:
            return CostEstimate(
                estimated_cost=CostLevel.UNKNOWN,
                warnings=["no executor bound for estimation"],
            )
        try:
            if req.capability == Capability.AGGREGATE:
                raw = await self._executor.explain_aggregate_stats(req.resource, req.pipeline or [])
            elif req.capability in (Capability.READ, Capability.COUNT):
                raw = await self._executor.explain_find_stats(
                    req.resource, req.filter or {}, req.projection
                )
            else:
                return CostEstimate(
                    estimated_cost=CostLevel.UNKNOWN,
                    warnings=[f"estimation not supported for {req.capability.value}"],
                )
        except Exception as exc:  # explain itself failed — degrade gracefully
            return CostEstimate(
                estimated_cost=CostLevel.UNKNOWN,
                warnings=[f"explain failed: {type(exc).__name__}"],
            )
        return normalize_mongo_explain(raw)

    # ── Introspection delegation ─────────────────────────────────────────────
    async def schema(self, resource: str, sample_size: int | None = None) -> dict:
        if self._executor is None:
            return {}
        return await self._executor.collection_schema(resource, [], sample_size)

    async def list_resources(self) -> list[str]:
        if self._executor is None:
            return []
        return await self._executor.list_collections()
