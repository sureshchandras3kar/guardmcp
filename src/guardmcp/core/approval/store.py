import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from ..models.domain import RiskLevel
from .models import ApprovalRequest


class ApprovalStore:
    def __init__(self, timeout_seconds: float = 300.0) -> None:
        self._timeout = timeout_seconds
        self._store: dict[str, ApprovalRequest] = {}
        self._events: dict[str, asyncio.Event] = {}

    def create(
        self,
        *,
        agent: str,
        action: str,
        collection: str,
        risk: RiskLevel,
        reason: str,
        params: dict[str, Any],
    ) -> ApprovalRequest:
        req = ApprovalRequest(
            approval_id=str(uuid4()),
            agent=agent,
            action=action,
            collection=collection,
            risk=risk,
            reason=reason,
            params=params,
            created_at=datetime.now(UTC),
        )
        self._store[req.approval_id] = req
        self._events[req.approval_id] = asyncio.Event()
        return req

    def get(self, approval_id: str) -> ApprovalRequest | None:
        return self._store.get(approval_id)

    def list_pending(self) -> list[ApprovalRequest]:
        return [r for r in self._store.values() if r.status == "pending"]

    def resolve(self, approval_id: str, *, approved: bool) -> ApprovalRequest | None:
        req = self._store.get(approval_id)
        if req is None or req.status != "pending":
            return None
        req.status = "approved" if approved else "denied"
        event = self._events.get(approval_id)
        if event:
            event.set()
        return req

    def prune(self, max_age_seconds: float = 3600.0) -> int:
        """Remove resolved approvals older than max_age_seconds. Returns count pruned."""
        from datetime import datetime

        now = datetime.now(UTC)
        to_delete = [
            aid
            for aid, req in self._store.items()
            if req.status != "pending" and (now - req.created_at).total_seconds() > max_age_seconds
        ]
        for aid in to_delete:
            self._store.pop(aid, None)
            self._events.pop(aid, None)
        return len(to_delete)

    def shutdown(self) -> int:
        """
        Deny all pending approvals immediately and signal their events.
        Call on process shutdown so in-flight wait_for_decision() coroutines
        return promptly instead of hanging until timeout.
        Returns count of approvals denied.
        """
        pending = [aid for aid, req in self._store.items() if req.status == "pending"]
        for aid in pending:
            self._store[aid].status = "denied"
            event = self._events.get(aid)
            if event:
                event.set()
        return len(pending)

    async def wait_for_decision(self, approval_id: str) -> str:
        event = self._events.get(approval_id)
        if event is None:
            return "denied"
        try:
            await asyncio.wait_for(event.wait(), timeout=self._timeout)
        except TimeoutError:
            req = self._store.get(approval_id)
            if req and req.status == "pending":
                req.status = "denied"
            return "denied"
        req = self._store.get(approval_id)
        return req.status if req else "denied"
