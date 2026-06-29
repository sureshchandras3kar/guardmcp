"""Tests for the approval API health endpoints (k8s liveness/readiness).

``/healthz`` is always 200. ``/readyz`` reflects the readiness probe: a probe
returning (True, "") → 200; (False, "detail") → 503 with detail; a probe that
RAISES → 503 (the endpoint must never crash). ``/health`` and ``/ready`` are
backward-compat aliases and also respond 200. Driven with FastAPI's TestClient.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from guardmcp.api.approval import build_approval_app
from guardmcp.core.approval.store import ApprovalStore


def _client(readiness=None):
    app = build_approval_app(ApprovalStore(), api_token="", readiness=readiness)
    return TestClient(app)


def test_healthz_ok():
    resp = _client().get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_health_alias_ok():
    assert _client().get("/health").status_code == 200


def test_readyz_no_probe_is_ready():
    # With no probe wired, /readyz falls back to liveness (always ready).
    resp = _client().get("/readyz")
    assert resp.status_code == 200


def test_readyz_probe_ready():
    async def probe():
        return (True, "")

    resp = _client(readiness=probe).get("/readyz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"


def test_readyz_probe_not_ready_returns_503_with_detail():
    async def probe():
        return (False, "policy not loaded")

    resp = _client(readiness=probe).get("/readyz")
    assert resp.status_code == 503
    assert resp.json()["detail"] == "policy not loaded"


def test_readyz_probe_that_raises_does_not_crash():
    async def probe():
        raise RuntimeError("backend exploded")

    resp = _client(readiness=probe).get("/readyz")
    # Endpoint catches the exception → 503, never a 500/crash.
    assert resp.status_code == 503
    assert resp.json()["status"] == "not_ready"


def test_ready_alias_reflects_probe():
    async def probe():
        return (True, "")

    assert _client(readiness=probe).get("/ready").status_code == 200


def test_health_endpoints_need_no_auth():
    # Even with a token configured, health endpoints stay open for k8s probes.
    app = build_approval_app(ApprovalStore(), api_token="secret", readiness=None)
    client = TestClient(app)
    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 200
