"""Shared harness for live-MongoDB verification (real testcontainers-backed
mongod, real motor driver — no mongomock anywhere in this package). One
container is shared for the whole session (fast); each test gets its OWN
fresh logical database name (cheap isolation, no cross-test data leakage —
MongoDB creates databases/collections lazily on first write).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest

from guardmcp.core.approval.store import ApprovalStore
from guardmcp.core.audit.logger import AuditLogger
from guardmcp.core.pipeline import GuardPipeline
from guardmcp.core.policy.engine import PolicyEngine
from guardmcp.core.policy.loader import PolicyLoader
from guardmcp.core.ratelimit.limiter import RateLimiter
from guardmcp.core.registry.connections import ConnectionRegistry, reset_active
from guardmcp.core.risk.engine import RiskEngine
from guardmcp.plugins.mongodb.client import MongoClient
from guardmcp.plugins.mongodb.executor import MongoExecutor
from guardmcp.plugins.mongodb.plugin import MongoPlugin

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
def mongo_uri() -> Iterator[str]:
    pytest.importorskip("testcontainers")
    pytest.importorskip("motor")
    from testcontainers.mongodb import MongoDbContainer

    try:
        container = MongoDbContainer("mongo:7")
        container.start()
    except Exception as exc:  # noqa: BLE001 - any startup failure -> clean skip
        pytest.skip(f"docker unavailable: {exc!r}")
        return
    try:
        yield container.get_connection_url()
    finally:
        container.stop()


@pytest.fixture
def db_name() -> str:
    """A fresh, never-before-used logical database name per test."""
    return f"livetest_{uuid.uuid4().hex[:10]}"


@pytest.fixture(autouse=True)
def _reset_connection_state():
    """_active_connection/_active_databases are module-level ContextVars —
    reset around every test so one test's switch_connection()/use_database()
    can never leak into the next (same reasoning as test_connections.py)."""
    reset_active()
    yield
    reset_active()


def _client_factory(uri, database, *, min_pool_size, max_pool_size):
    return MongoClient(uri, database, min_pool_size=min_pool_size, max_pool_size=max_pool_size)


def build_pipeline(
    tmp_path,
    mongo_uri: str,
    db_name: str,
    policy_yaml: str,
    *,
    extra_connections: dict[str, str] | None = None,
    hmac_secret: str = "livetest-secret",
    rate_limit_rps: float = 0.0,
    rate_limit_burst: int = 0,
):
    """Build a REAL GuardPipeline (real MongoExecutor/MongoClient/MongoPlugin,
    real ConnectionRegistry) wired to the live testcontainers mongod.

    `extra_connections`: {connection_name: database_name} — additional named
    connections against the SAME container (different logical databases),
    for multi-connection scenarios. All share `db_name` as "default" unless
    overridden here.

    Returns (pipeline, registry, audit_path).
    """
    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text(policy_yaml)
    loader = PolicyLoader(policy_path)
    loader.load()

    registry = ConnectionRegistry(client_factory=_client_factory)
    registry.register("default", mongo_uri, db_name)
    for name, extra_db in (extra_connections or {}).items():
        registry.register(name, mongo_uri, extra_db)

    for name in registry.list_names():
        entry = registry.get(name)
        entry.executor = MongoExecutor(entry.client)
        entry.plugin = MongoPlugin(executor=entry.executor, client=entry.client)

    audit_path = tmp_path / "audit.jsonl"
    limiter = (
        RateLimiter(rps=rate_limit_rps, burst=rate_limit_burst) if rate_limit_rps > 0 else None
    )
    pipeline = GuardPipeline(
        policy_loader=loader,
        policy_engine=PolicyEngine(),
        risk_engine=RiskEngine(),
        audit_logger=AuditLogger(audit_path, hmac_secret=hmac_secret),
        approval_store=ApprovalStore(timeout_seconds=2.0),
        executor=registry.get("default").executor,
        registry=registry,
        limiter=limiter,
    )
    return pipeline, registry, audit_path


# ── 3 policy variants (§1 of the plan) ──────────────────────────────────────


def readonly_allow_all_policy(agent: str = "claude") -> str:
    return f"""
agent: {agent}
mode: readonly
collections:
  allow: ["*"]
"""


def readwrite_masked_policy(
    agent: str = "claude",
    collections_allow: list[str] | None = None,
    mask_fields: list[str] | None = None,
    approval_high: bool = True,
    approval_critical: bool = True,
) -> str:
    collections_allow = collections_allow or ["*"]
    mask_fields = mask_fields if mask_fields is not None else ["ssn", "email"]
    allow_yaml = "\n".join(f'    - "{c}"' for c in collections_allow)
    mask_block = (
        "mask_fields:\n" + "\n".join(f"  - {f}" for f in mask_fields) + "\n" if mask_fields else ""
    )
    return f"""
agent: {agent}
mode: readwrite
collections:
  allow:
{allow_yaml}
{mask_block}approval:
  high: {str(approval_high).lower()}
  critical: {str(approval_critical).lower()}
"""


def multi_db_policy(
    agent: str = "claude",
    databases_allow: list[str] | None = None,
    per_db_mask: dict[str, list[str]] | None = None,
) -> str:
    databases_allow = databases_allow or []
    per_db_mask = per_db_mask or {}
    dbs_yaml = "\n".join(f"  - {d}" for d in databases_allow)
    scopes = []
    for db, masks in per_db_mask.items():
        mask_lines = "\n".join(f"      - {m}" for m in masks)
        scopes.append(
            f"  {db}:\n    collections:\n      allow: [\"*\"]\n    mask_fields:\n{mask_lines}"
        )
    databases_block = "databases: {}" if not scopes else "databases:\n" + "\n".join(scopes)
    return f"""
agent: {agent}
mode: readwrite
collections:
  allow: ["*"]
databases_allow:
{dbs_yaml}
{databases_block}
approval:
  high: true
  critical: true
"""
