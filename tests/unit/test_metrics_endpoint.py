"""Tests for the approval API's /metrics Prometheus endpoint. No auth required
(same posture as /healthz — no PII, just per-action/status request counters).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from guardmcp.api.approval import build_approval_app
from guardmcp.core import metrics
from guardmcp.core.approval.store import ApprovalStore


def setup_function():
    metrics.reset()


def _client(api_token: str = "") -> TestClient:
    app = build_approval_app(ApprovalStore(), api_token=api_token)
    return TestClient(app)


def test_metrics_endpoint_returns_200_and_plaintext():
    resp = _client().get("/metrics")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]


def test_metrics_endpoint_reflects_recorded_counters():
    metrics.increment("guardmcp_requests_total", action="find", status="allowed")
    resp = _client().get("/metrics")
    assert 'guardmcp_requests_total{action="find",status="allowed"} 1' in resp.text


def test_metrics_endpoint_needs_no_auth_even_with_token_configured():
    metrics.increment("guardmcp_requests_total", action="find", status="allowed")
    client = _client(api_token="secret")
    resp = client.get("/metrics")
    assert resp.status_code == 200


def test_metrics_endpoint_empty_registry_is_still_200():
    resp = _client().get("/metrics")
    assert resp.status_code == 200
    assert resp.text == ""
