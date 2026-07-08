"""Tests for the approval REST API's actual approval endpoints (list/get/decide)
and token auth — previously untested (only health/DNS-rebinding had coverage).

Uses the REAL ApprovalStore (not a fake) — its create()/get()/list_pending()/
resolve() signatures are exercised directly, so a signature drift here fails
loud instead of hiding behind a lenient fake.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from guardmcp.api.approval import build_approval_app
from guardmcp.core.approval.store import ApprovalStore
from guardmcp.core.models.domain import RiskLevel


def _client(api_token: str = "") -> tuple[TestClient, ApprovalStore]:
    store = ApprovalStore()
    app = build_approval_app(store, api_token=api_token)
    return TestClient(app), store


def _make_pending(store: ApprovalStore, **overrides):
    kw = {
        "agent": "claude",
        "action": "delete_many",
        "collection": "users",
        "risk": RiskLevel.CRITICAL,
        "reason": "test",
        "params": {"filter": {}},
    }
    kw.update(overrides)
    return store.create(**kw)


# ── list_pending ─────────────────────────────────────────────────────────────


def test_list_pending_empty():
    client, _ = _client()
    resp = client.get("/approvals/pending")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_pending_returns_only_pending_not_resolved():
    client, store = _client()
    pending = _make_pending(store)
    resolved = _make_pending(store, collection="orders")
    store.resolve(resolved.approval_id, approved=True)

    resp = client.get("/approvals/pending")
    assert resp.status_code == 200
    ids = [r["approval_id"] for r in resp.json()]
    assert ids == [pending.approval_id]


# ── get by id ────────────────────────────────────────────────────────────────


def test_get_approval_found():
    client, store = _client()
    req = _make_pending(store)
    resp = client.get(f"/approvals/{req.approval_id}")
    assert resp.status_code == 200
    assert resp.json()["approval_id"] == req.approval_id
    assert resp.json()["risk"] == "CRITICAL"


def test_get_approval_not_found_404():
    client, _ = _client()
    resp = client.get("/approvals/does-not-exist")
    assert resp.status_code == 404


# ── decide ───────────────────────────────────────────────────────────────────


def test_decide_approve():
    client, store = _client()
    req = _make_pending(store)
    resp = client.post(f"/approvals/{req.approval_id}/decide", json={"approved": True})
    assert resp.status_code == 200
    assert resp.json() == {"approval_id": req.approval_id, "status": "approved"}
    assert store.get(req.approval_id).status == "approved"


def test_decide_deny():
    client, store = _client()
    req = _make_pending(store)
    resp = client.post(f"/approvals/{req.approval_id}/decide", json={"approved": False})
    assert resp.status_code == 200
    assert resp.json()["status"] == "denied"


def test_decide_not_found_404():
    client, _ = _client()
    resp = client.post("/approvals/does-not-exist/decide", json={"approved": True})
    assert resp.status_code == 404


def test_decide_already_resolved_404():
    client, store = _client()
    req = _make_pending(store)
    store.resolve(req.approval_id, approved=True)
    resp = client.post(f"/approvals/{req.approval_id}/decide", json={"approved": False})
    assert resp.status_code == 404


# ── token auth (S-2: constant-time comparison, all 3 approval endpoints) ────


def test_no_token_configured_allows_unauthenticated_access():
    client, store = _client(api_token="")
    req = _make_pending(store)
    assert client.get("/approvals/pending").status_code == 200
    assert client.get(f"/approvals/{req.approval_id}").status_code == 200


def test_missing_token_rejected_when_configured():
    client, _ = _client(api_token="secret")
    resp = client.get("/approvals/pending")
    assert resp.status_code == 403


def test_wrong_token_rejected():
    client, _ = _client(api_token="secret")
    resp = client.get("/approvals/pending", headers={"X-Approval-Token": "wrong"})
    assert resp.status_code == 403


def test_correct_token_allows_access():
    client, _ = _client(api_token="secret")
    resp = client.get("/approvals/pending", headers={"X-Approval-Token": "secret"})
    assert resp.status_code == 200


def test_token_required_on_get_by_id():
    client, store = _client(api_token="secret")
    req = _make_pending(store)
    assert client.get(f"/approvals/{req.approval_id}").status_code == 403
    resp = client.get(
        f"/approvals/{req.approval_id}", headers={"X-Approval-Token": "secret"}
    )
    assert resp.status_code == 200


def test_token_required_on_decide():
    client, store = _client(api_token="secret")
    req = _make_pending(store)
    denied = client.post(f"/approvals/{req.approval_id}/decide", json={"approved": True})
    assert denied.status_code == 403
    # The unauthenticated attempt must NOT have resolved it.
    assert store.get(req.approval_id).status == "pending"

    allowed = client.post(
        f"/approvals/{req.approval_id}/decide",
        json={"approved": True},
        headers={"X-Approval-Token": "secret"},
    )
    assert allowed.status_code == 200
