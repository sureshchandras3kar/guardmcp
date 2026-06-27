"""Tests for the human-in-the-loop approval store."""

from guardmcp.core.approval.store import ApprovalStore
from guardmcp.core.models.domain import RiskLevel


def _create(store, agent="a"):
    return store.create(
        agent=agent,
        action="delete_many",
        collection="customers",
        risk=RiskLevel.HIGH,
        reason="bulk delete",
        params={"filter": {}},
    )


async def test_create_get_list_pending():
    store = ApprovalStore(timeout_seconds=1.0)
    req = _create(store)
    assert req.status == "pending"
    assert store.get(req.approval_id) is req
    assert req in store.list_pending()


async def test_resolve_approved():
    store = ApprovalStore(timeout_seconds=1.0)
    req = _create(store)
    store.resolve(req.approval_id, approved=True)
    assert await store.wait_for_decision(req.approval_id) == "approved"


async def test_resolve_denied():
    store = ApprovalStore(timeout_seconds=1.0)
    req = _create(store)
    store.resolve(req.approval_id, approved=False)
    assert await store.wait_for_decision(req.approval_id) == "denied"


async def test_timeout_denies():
    store = ApprovalStore(timeout_seconds=0.01)
    req = _create(store)
    # No resolve — wait times out and is denied.
    assert await store.wait_for_decision(req.approval_id) == "denied"


async def test_shutdown_denies_all_pending():
    store = ApprovalStore(timeout_seconds=5.0)
    r1 = _create(store, "a1")
    r2 = _create(store, "a2")
    assert store.shutdown() == 2
    assert store.get(r1.approval_id).status == "denied"
    assert store.get(r2.approval_id).status == "denied"
    # Pending waiters return promptly with "denied" rather than hanging.
    assert await store.wait_for_decision(r1.approval_id) == "denied"


async def test_prune_removes_resolved():
    store = ApprovalStore(timeout_seconds=1.0)
    req = _create(store)
    store.resolve(req.approval_id, approved=True)
    removed = store.prune(max_age_seconds=0)
    assert removed == 1
    assert store.get(req.approval_id) is None


async def test_prune_shrinks_store_and_events_in_lockstep():
    # Resolved entries older than max_age must be dropped from BOTH the _store
    # and _events dicts so neither grows unbounded over the process lifetime.
    store = ApprovalStore(timeout_seconds=1.0)
    resolved = [_create(store, f"r{i}") for i in range(3)]
    pending = _create(store, "p")
    for req in resolved:
        store.resolve(req.approval_id, approved=True)

    assert len(store._store) == 4
    assert len(store._events) == 4

    removed = store.prune(max_age_seconds=0)

    assert removed == 3
    # Pending entry survives; both dicts shrink in lockstep to just it.
    assert len(store._store) == 1
    assert len(store._events) == 1
    assert pending.approval_id in store._store
    assert pending.approval_id in store._events
