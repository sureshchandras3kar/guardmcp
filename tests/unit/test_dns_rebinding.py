"""DNS-rebinding / Host-header validation on the approval API."""

from fastapi.testclient import TestClient

from guardmcp.api.approval import build_approval_app
from guardmcp.core.approval.store import ApprovalStore


def _client(allowed_hosts):
    return TestClient(build_approval_app(ApprovalStore(), allowed_hosts=allowed_hosts))


def test_allowed_host_passes():
    c = _client(["localhost", "127.0.0.1"])
    assert c.get("/healthz", headers={"host": "localhost"}).status_code == 200


def test_port_is_stripped_before_matching():
    c = _client(["127.0.0.1"])
    assert c.get("/healthz", headers={"host": "127.0.0.1:8001"}).status_code == 200


def test_unknown_host_rejected():
    c = _client(["localhost", "127.0.0.1"])
    # DNS-rebinding attempt: browser tricked into resolving attacker domain to loopback.
    assert c.get("/healthz", headers={"host": "attacker.example"}).status_code == 400


def test_unknown_host_rejected_on_approvals_route():
    c = _client(["localhost"])
    # The protection covers the whole app, incl. the CRITICAL-write decide route.
    r = c.get("/approvals/pending", headers={"host": "evil.test"})
    assert r.status_code == 400


def test_wildcard_disables_protection():
    c = _client(["*"])
    assert c.get("/healthz", headers={"host": "anything.goes"}).status_code == 200


def test_none_disables_protection_backcompat():
    # No allowed_hosts → middleware not added (back-compat / stdio has no port).
    c = TestClient(build_approval_app(ApprovalStore()))
    assert c.get("/healthz", headers={"host": "anything"}).status_code == 200
