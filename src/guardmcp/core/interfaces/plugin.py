"""
DatabasePlugin — THE public plugin contract for third-party backends.

This is the ONLY interface a new backend (PostgreSQL, MySQL, …) implements. It is
capability-based and database-neutral. GuardMCP bridges it to the internal
execution interface (core/interfaces/backend.py, the Mongo-shaped `Backend`)
via CapabilityExecutorAdapter — plugins never implement `Backend` directly.

See docs/ARCHITECTURE.md for the public-vs-internal interface table and the
request/result flow.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from .capability import Capability, CapabilityRequest, CapabilityResult
from .cost import CostEstimate, CostLevel


@dataclass(frozen=True)
class AlternativeRequest:
    """A dialect-specific alternative form of a base request, produced by a
    plugin (see DatabasePlugin.alternative_requests).

    The whole point of this type is to keep core/planning database-agnostic: the
    planner asks the active plugin for alternatives and wraps whatever it returns
    into an AlternativePlan WITHOUT knowing anything about the dialect. All
    dialect tokens (a Mongo `$match`/`$limit` pipeline, a SQL sub-select, …) live
    inside `request`, which the plugin builds; core never constructs them.

    - request: the not-yet-executed CapabilityRequest for the alternative form.
    - strategy: human-facing label for the plan (e.g. "aggregation").
    - complexity: relative complexity bucket surfaced to the ranker.
    - tradeoff: one-line explanation of what this form buys / costs.
    """

    request: CapabilityRequest
    strategy: str
    complexity: str = "medium"
    tradeoff: str = ""


class DatabasePlugin(ABC):
    """Public, capability-based contract for a database backend plugin."""

    name: str
    api_version: str = "1.0"
    supported: frozenset[Capability]

    # ── Transaction seam (Risk #10) ─────────────────────────────────────────
    # A plugin that can run multi-statement transactions sets this True and
    # overrides begin/commit/rollback. The default is a no-op contract so every
    # existing plugin remains valid WITHOUT change. This is only the SEAM — the
    # pipeline does not thread tx_id through execution yet; CapabilityRequest.tx_id
    # makes a transaction handle expressible once a backend opts in.
    supports_transactions: bool = False

    # ── #7: static capability manifest (read WITHOUT instantiating/connecting) ──
    # Read class attrs only — no __init__, no DSN, no optional driver import. This
    # lets a registry/tooling enumerate what a backend supports before any
    # connection (and even when the backend's optional driver isn't installed).
    dialect_features: dict = {}

    @classmethod
    def manifest(cls) -> dict:
        """Return {name, api_version, supported, dialect_features} from class
        attrs WITHOUT an instance or connection. SQL plugins override
        dialect_features (placeholder style, RETURNING support, etc.)."""
        return {
            "name": getattr(cls, "name", cls.__name__),
            "api_version": getattr(cls, "api_version", "1.0"),
            "supported": sorted(c.value for c in getattr(cls, "supported", frozenset())),
            "dialect_features": dict(getattr(cls, "dialect_features", {})),
        }

    @abstractmethod
    async def connect(self, dsn: str, options: dict) -> None: ...
    @abstractmethod
    async def health(self) -> bool: ...
    @abstractmethod
    async def close(self) -> None: ...
    @abstractmethod
    async def execute(self, req: CapabilityRequest) -> CapabilityResult: ...
    @abstractmethod
    async def schema(self, resource: str, sample_size: int | None = None) -> dict: ...
    @abstractmethod
    async def list_resources(self) -> list[str]: ...
    @abstractmethod
    def validate_request(self, req: CapabilityRequest) -> None: ...

    def cross_resource_refs(self, req: CapabilityRequest) -> set[str]:
        return set()

    # ── Alternative plan generation (NOT abstract: safe default) ─────────────
    # Given a base (not-yet-executed) request, return dialect-specific ALTERNATIVE
    # forms of it (e.g. Mongo turns a filtered read into a $match/$limit aggregate
    # pipeline). This keeps core/planning free of any dialect tokens: the planner
    # asks the active plugin and wraps whatever comes back. Default `[]` so every
    # existing / third-party plugin (and SQL backends that have no cheaper
    # alternative form) stays valid unchanged.
    def alternative_requests(self, req: CapabilityRequest) -> list[AlternativeRequest]:
        return []

    async def relationships(self, resources: list[str]) -> list[dict]:
        """Return normalized relationship hints among `resources`.

        Each dict: {from_resource, from_field, to_resource, to_field, kind,
        confidence, evidence}. Safe default `[]` so backends that cannot infer
        relationships (and all not-yet-updated plugins) stay valid unchanged.
        """
        return []

    # ── Cost estimation (NOT abstract: safe default) ─────────────────────────
    # A backend that can estimate an operation's cost via its native explain
    # overrides this and NORMALIZES the result into a CostEstimate (never the raw
    # plan). The default returns UNKNOWN so existing / third-party plugins keep
    # working unchanged. `req` describes the operation to estimate (its target
    # capability + filter/pipeline/resource), NOT a separate ESTIMATE action.
    async def estimate(self, req: CapabilityRequest) -> CostEstimate:
        return CostEstimate(
            estimated_cost=CostLevel.UNKNOWN,
            warnings=["estimation not supported by this backend"],
        )

    # ── Transaction methods (NOT abstract: safe no-op defaults) ──────────────
    async def begin(self) -> str | None:
        """Begin a transaction and return its tx_id, or None if unsupported."""
        return None

    async def commit(self, tx_id: str) -> None:
        """Commit the transaction identified by tx_id. No-op by default."""
        return None

    async def rollback(self, tx_id: str) -> None:
        """Roll back the transaction identified by tx_id. No-op by default."""
        return None
