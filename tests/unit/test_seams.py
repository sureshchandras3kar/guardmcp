"""Seam conformance tests (Risks #4, #5, #7, #8).

These assert the shipped single-process defaults formally satisfy the new
Protocols, that attribution + identity defaults are behavior-preserving, and that
the active-connection ContextVar is per-context isolated.
"""

import contextvars
import json
from pathlib import Path

from guardmcp.core.approval.store import ApprovalStore
from guardmcp.core.audit.logger import AuditLogger
from guardmcp.core.interfaces.identity import (
    PrincipalResolver,
    StaticPrincipalResolver,
)
from guardmcp.core.interfaces.stores import (
    ApprovalStoreProtocol,
    AuditSinkProtocol,
    RateLimiterProtocol,
)
from guardmcp.core.ratelimit.limiter import RateLimiter
from guardmcp.core.registry.connections import (
    ConnectionRegistry,
    _active_connection,
    reset_active,
)

# ── Risk #4: governance-state Protocol conformance ────────────────────────────


def test_approval_store_satisfies_protocol():
    assert isinstance(ApprovalStore(), ApprovalStoreProtocol)


def test_rate_limiter_satisfies_protocol():
    assert isinstance(RateLimiter(), RateLimiterProtocol)


def test_audit_logger_satisfies_protocol(tmp_path: Path):
    logger = AuditLogger(tmp_path / "audit.jsonl")
    assert isinstance(logger, AuditSinkProtocol)


# ── Risk #7: principal resolver default preserves behavior ────────────────────


def test_static_principal_resolver_returns_configured_agent():
    resolver = StaticPrincipalResolver("agent-x")
    assert isinstance(resolver, PrincipalResolver)
    assert resolver.resolve({}) == "agent-x"
    assert resolver.resolve({"X-GuardMCP-Agent": "ignored"}) == "agent-x"


# ── Risk #5: node_id attribution ──────────────────────────────────────────────


async def test_audit_record_carries_node_id(tmp_path: Path):
    path = tmp_path / "audit.jsonl"
    logger = AuditLogger(path, node_id="r1")
    record = logger.build(agent="a", collection="c", action="find", status="allowed")
    assert record.node_id == "r1"
    await logger.log(record)
    await logger.aclose()

    lines = [ln for ln in path.read_text().splitlines() if ln.strip()]
    assert len(lines) == 1
    assert json.loads(lines[0])["node_id"] == "r1"


def test_audit_record_node_id_defaults_empty(tmp_path: Path):
    # Default (single-process) logger stamps node_id="" — unchanged behavior.
    logger = AuditLogger(tmp_path / "audit.jsonl")
    record = logger.build(agent="a", collection="c", action="find", status="allowed")
    assert record.node_id == ""


# ── Risk #8: ContextVar isolation across copied contexts ──────────────────────


def test_active_connection_isolated_across_contexts():
    reg = ConnectionRegistry()
    # Register two names directly (no client_factory needed for switch()).
    from guardmcp.core.registry.connections import ConnectionEntry

    reg._registry["alpha"] = ConnectionEntry(client=object(), database="a")
    reg._registry["beta"] = ConnectionEntry(client=object(), database="b")

    seen: dict[str, str] = {}

    def run_alpha():
        reg.switch("alpha")
        seen["alpha"] = reg.active_name()

    def run_beta():
        reg.switch("beta")
        seen["beta"] = reg.active_name()

    parent_before = _active_connection.get()
    ctx_a = contextvars.copy_context()
    ctx_b = contextvars.copy_context()
    ctx_a.run(run_alpha)
    ctx_b.run(run_beta)

    # Each copied context saw only its own switch — no cross-contamination.
    assert seen == {"alpha": "alpha", "beta": "beta"}
    # The parent context is untouched by switches made inside copied contexts.
    assert _active_connection.get() == parent_before


def test_reset_active_only_affects_current_context():
    _active_connection.set("default")

    def run():
        _active_connection.set("alpha")
        reset_active()
        return _active_connection.get()

    assert contextvars.copy_context().run(run) == "default"
