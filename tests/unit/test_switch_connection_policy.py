import json

import pytest

from guardmcp.core.approval.store import ApprovalStore
from guardmcp.core.audit.logger import AuditLogger
from guardmcp.core.pipeline import GuardPipeline
from guardmcp.core.policy.engine import PolicyEngine
from guardmcp.core.policy.loader import PolicyLoader
from guardmcp.core.risk.engine import RiskEngine


class _StubRegistry:
    """Minimal registry: every switch to a known name succeeds."""

    def __init__(self, names):
        self._names = set(names)
        self.active = "default"

    def switch(self, name):
        if name in self._names:
            self.active = name
            return True
        return False

    def get_active(self):
        return None


def _build_pipeline(tmp_path, policy_yaml, registry):
    pf = tmp_path / "policy.yaml"
    pf.write_text(policy_yaml)
    loader = PolicyLoader(pf)
    loader.load()
    return GuardPipeline(
        policy_loader=loader,
        policy_engine=PolicyEngine(),
        risk_engine=RiskEngine(),
        audit_logger=AuditLogger(tmp_path / "audit.jsonl"),
        approval_store=ApprovalStore(timeout_seconds=1.0),
        executor=object(),
        registry=registry,
    )


def _read_audit(tmp_path):
    p = tmp_path / "audit.jsonl"
    lines = [json.loads(line) for line in p.read_text().splitlines() if line.strip()]
    return lines


@pytest.mark.asyncio
async def test_switch_allowed_when_in_allowlist(tmp_path):
    reg = _StubRegistry(["mongo_prod", "mongo_stg"])
    pipe = _build_pipeline(
        tmp_path,
        "agent: a\nmode: readonly\nconnections_allow: [mongo_prod]\n",
        reg,
    )
    ok = await pipe.switch_connection_audited("a", "mongo_prod")
    assert ok is True
    assert reg.active == "mongo_prod"
    audit = _read_audit(tmp_path)
    assert any(r["action"] == "switch_connection" and r["status"] == "allowed" for r in audit)


@pytest.mark.asyncio
async def test_switch_denied_when_not_in_allowlist(tmp_path):
    reg = _StubRegistry(["mongo_prod", "mongo_stg"])
    pipe = _build_pipeline(
        tmp_path,
        "agent: a\nmode: readonly\nconnections_allow: [mongo_prod]\n",
        reg,
    )
    ok = await pipe.switch_connection_audited("a", "mongo_stg")
    assert ok is False
    # Active connection was NOT changed.
    assert reg.active == "default"
    audit = _read_audit(tmp_path)
    assert any(r["action"] == "switch_connection" and r["status"] == "denied" for r in audit)


@pytest.mark.asyncio
async def test_empty_allowlist_permits_all(tmp_path):
    reg = _StubRegistry(["mongo_prod"])
    pipe = _build_pipeline(
        tmp_path,
        "agent: a\nmode: readonly\n",  # no connections_allow
        reg,
    )
    ok = await pipe.switch_connection_audited("a", "mongo_prod")
    assert ok is True
