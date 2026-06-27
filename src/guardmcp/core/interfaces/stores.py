"""
Governance-state seams (Risk #4).

These are the seams for distributed backends (Redis approvals, shared-token-
bucket rate limiting, Kafka/S3 audit sink). The shipped in-memory/file impls
(ApprovalStore, RateLimiter, AuditLogger) are the single-process defaults; swap
via the composition layer (__main__) without changing core.

The GuardPipeline is typed against these Protocols, not the concrete classes, so
a Redis/Kafka/QLDB implementation drops in by satisfying the same surface — no
call-site changes. All Protocols are runtime_checkable so conformance can be
asserted with isinstance() in tests.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from ..models.domain import RiskLevel


@runtime_checkable
class ApprovalStoreProtocol(Protocol):
    """Durable surface for approval-request lifecycle.

    A distributed impl (e.g. Redis) replaces the in-memory dict + asyncio.Event
    with a shared store + pub/sub so any replica can resolve an approval created
    on another. Method shapes mirror the shipped ApprovalStore.
    """

    def create(
        self,
        *,
        agent: str,
        action: str,
        collection: str,
        risk: RiskLevel,
        reason: str,
        params: dict[str, Any],
    ) -> Any: ...

    def get(self, approval_id: str) -> Any: ...

    def list_pending(self) -> list[Any]: ...

    def resolve(self, approval_id: str, *, approved: bool) -> Any: ...

    async def wait_for_decision(self, approval_id: str) -> str: ...

    def shutdown(self) -> int: ...

    def prune(self, max_age_seconds: float = ...) -> int: ...


@runtime_checkable
class RateLimiterProtocol(Protocol):
    """Per-agent admission control.

    A distributed impl (shared token bucket in Redis) lets the limit hold across
    replicas instead of per-process. `check` returns True if allowed.
    """

    @property
    def enabled(self) -> bool: ...

    async def check(self, agent: str) -> bool: ...


@runtime_checkable
class AuditSinkProtocol(Protocol):
    """Durable-write surface for the audit trail.

    The shipped AuditLogger writes a per-process HMAC-chained JSONL file. A
    centralized, tamper-evident impl (Kafka+KMS / QLDB / append-only S3) satisfies
    this same surface and is aggregated by AuditRecord.node_id across replicas.
    """

    def build(
        self,
        *,
        agent: str,
        collection: str,
        action: str,
        status: str,
        reason: str | None = ...,
        risk: str | None = ...,
        request_id: str | None = ...,
        params: dict[str, Any] | None = ...,
    ) -> Any: ...

    async def log(self, record: Any) -> None: ...

    async def aclose(self) -> None: ...
