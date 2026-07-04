"""
Multi-backend CONNECTION lifecycle / use-case coverage.

These tests exercise EVERY connection use case WITHOUT a live database:
  * MongoDB connections are built through build()'s real _mongo_client_factory
    backed by mongomock-motor (no real mongod needed).
  * SQL (postgres/mysql) connections are instantiated exactly as build() does —
    via register_sql_connections() — WITHOUT calling connect() (no asyncpg /
    aiomysql / live pool required).

ADDITIVE: nothing in src/ is modified; these only observe real APIs.
"""

from __future__ import annotations

import contextvars
import json

import pytest
from mongomock_motor import AsyncMongoMockClient

from guardmcp.__main__ import (
    _build_plugin_registry,
    build,
    register_sql_connections,
)
from guardmcp.config import ConnectionConfig, Settings
from guardmcp.core.approval.store import ApprovalStore
from guardmcp.core.audit.logger import AuditLogger
from guardmcp.core.interfaces.capability import ACTION_TO_CAPABILITY, Capability
from guardmcp.core.models.domain import Action
from guardmcp.core.pipeline import GuardPipeline
from guardmcp.core.policy.engine import PolicyEngine
from guardmcp.core.policy.loader import PolicyLoader
from guardmcp.core.registry.adapter import CapabilityExecutorAdapter
from guardmcp.core.registry.connections import (
    ConnectionRegistry,
    reset_active,
)
from guardmcp.core.registry.registry import PluginRegistry
from guardmcp.core.risk.engine import RiskEngine
from guardmcp.plugins.mongodb.executor import MongoExecutor
from guardmcp.plugins.mongodb.plugin import MongoPlugin
from guardmcp.plugins.mysql.plugin import MySQLPlugin
from guardmcp.plugins.postgres.plugin import PostgresPlugin
from guardmcp.server.tools._common import _capability_check

# ── Helpers ─────────────────────────────────────────────────────────────────


def _patch_mongo_factory(monkeypatch):
    """Replace MongoClient (used by build()'s _mongo_client_factory) with a
    mongomock-motor-backed stub so build() runs with NO real mongod."""

    class _MockMongoClient:
        def __init__(self, uri, database, *, min_pool_size=0, max_pool_size=100):
            self.uri = uri
            self.database = database
            self.min_pool_size = min_pool_size
            self.max_pool_size = max_pool_size
            self._client = AsyncMongoMockClient()
            self.closed = False

        def get_collection(self, name, database=None):
            return self._client[self.database][name]

        def get_db(self, database=None):
            return self._client[self.database]

        async def list_collection_names(self, database=None):
            return await self._client[self.database].list_collection_names()

        async def list_databases(self):
            return [{"name": self.database, "sizeOnDisk": 0}]

        def close(self):
            self.closed = True

    # build() imports MongoClient at module import time into __main__.
    monkeypatch.setattr("guardmcp.__main__.MongoClient", _MockMongoClient)
    return _MockMongoClient


def _settings(tmp_path, **kw):
    return Settings(
        policy_path=tmp_path / "policy.yaml",
        audit_log_path=tmp_path / "audit.jsonl",
        **kw,
    )


def _write_policy(tmp_path, body: str):
    pf = tmp_path / "policy.yaml"
    pf.write_text(body)
    return pf


@pytest.fixture(autouse=True)
def _reset_active_connection():
    """Each test starts and ends on the default active connection so a switch in
    one test never leaks into another via the process-global ContextVar default."""
    reset_active()
    yield
    reset_active()


# ── 1. Default-only build ────────────────────────────────────────────────────


def test_default_only_build(tmp_path, monkeypatch):
    _patch_mongo_factory(monkeypatch)
    _write_policy(tmp_path, "agent: default-agent\nmode: readonly\n")
    _mcp, _rest, ctx = build(_settings(tmp_path))

    registry = ctx.registry
    assert registry.list_names() == ["default"]
    entry = registry.get("default")
    assert isinstance(entry.executor, MongoExecutor)
    assert isinstance(entry.plugin, MongoPlugin)
    assert ctx.pipeline.active_connection() == "default"


# ── 2. Extra MongoDB connections via extra_connections ───────────────────────


def test_extra_mongo_connections_each_get_mongo_executor(tmp_path, monkeypatch):
    _patch_mongo_factory(monkeypatch)
    _write_policy(tmp_path, "agent: default-agent\nmode: readonly\n")
    settings = _settings(
        tmp_path,
        extra_connections={
            "staging": "mongodb://stg:27017",
            "analytics": "mongodb://an:27017",
        },
    )
    _mcp, _rest, ctx = build(settings)

    registry = ctx.registry
    assert set(registry.list_names()) == {"default", "staging", "analytics"}
    for name in ("default", "staging", "analytics"):
        entry = registry.get(name)
        assert isinstance(entry.executor, MongoExecutor)
        assert isinstance(entry.plugin, MongoPlugin)


# ── 3. Typed SQL connections via GUARDMCP_CONNECTIONS JSON ───────────────────


def test_typed_sql_connections_use_adapter_and_carry_options(tmp_path, monkeypatch):
    _patch_mongo_factory(monkeypatch)
    _write_policy(tmp_path, "agent: default-agent\nmode: readonly\n")

    conns_json = json.dumps(
        {
            "pg": {
                "type": "postgres",
                "dsn": "postgres://u:p@h/app",
                "database": "app",
                "options": {"min_size": 1, "max_size": 10, "ssl": True},
            },
            "my": {
                "type": "mysql",
                "dsn": "mysql://u:p@h/shop",
                "database": "shop",
                "options": {"charset": "utf8mb4"},
            },
        }
    )
    # Settings parses GUARDMCP_CONNECTIONS JSON into dict[str, ConnectionConfig].
    monkeypatch.setenv("GUARDMCP_CONNECTIONS", conns_json)
    settings = _settings(tmp_path)
    assert "pg" in settings.connections and "my" in settings.connections

    _mcp, _rest, ctx = build(settings)
    registry = ctx.registry

    # Default mongo still present + untouched.
    assert isinstance(registry.get("default").executor, MongoExecutor)
    assert isinstance(registry.get("default").plugin, MongoPlugin)

    pg = registry.get("pg")
    assert isinstance(pg.executor, CapabilityExecutorAdapter)
    assert isinstance(pg.plugin, PostgresPlugin)
    assert pg.options == {"min_size": 1, "max_size": 10, "ssl": True}
    assert pg.database == "app"
    # Instantiated but NOT connected (no live pool in CI).
    assert pg.plugin._pool is None

    my = registry.get("my")
    assert isinstance(my.executor, CapabilityExecutorAdapter)
    assert isinstance(my.plugin, MySQLPlugin)
    assert my.options == {"charset": "utf8mb4"}
    assert my.database == "shop"
    assert my.plugin._pool is None


# ── 4. switch_connection: list / switch known / switch unknown ───────────────


def test_switch_connection_known_and_unknown(tmp_path, monkeypatch):
    _patch_mongo_factory(monkeypatch)
    _write_policy(tmp_path, "agent: default-agent\nmode: readonly\n")
    settings = _settings(tmp_path, extra_connections={"reporting": "mongodb://r:27017"})
    _mcp, _rest, ctx = build(settings)
    pipe = ctx.pipeline

    assert set(pipe.list_connections()) == {"default", "reporting"}
    assert pipe.switch_connection("reporting") is True
    assert pipe.active_connection() == "reporting"
    assert pipe.switch_connection("does-not-exist") is False
    # Failed switch leaves the previous active untouched.
    assert pipe.active_connection() == "reporting"


# ── 5. S-6 policy gate via switch_connection_audited ─────────────────────────


class _StubRegistry:
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


def _pipeline_with_registry(tmp_path, policy_yaml, registry):
    pf = _write_policy(tmp_path, policy_yaml)
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
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


@pytest.mark.asyncio
async def test_s6_switch_audited_allowed_in_allowlist(tmp_path):
    reg = _StubRegistry(["mongo_b", "mongo_c"])
    pipe = _pipeline_with_registry(
        tmp_path,
        "agent: a\nmode: readonly\nconnections_allow: [mongo_b]\n",
        reg,
    )
    assert await pipe.switch_connection_audited("a", "mongo_b") is True
    assert reg.active == "mongo_b"
    audit = _read_audit(tmp_path)
    assert any(r["action"] == "switch_connection" and r["status"] == "allowed" for r in audit)


@pytest.mark.asyncio
async def test_s6_switch_audited_denied_not_in_allowlist(tmp_path):
    reg = _StubRegistry(["mongo_b", "mongo_c"])
    pipe = _pipeline_with_registry(
        tmp_path,
        "agent: a\nmode: readonly\nconnections_allow: [mongo_b]\n",
        reg,
    )
    assert await pipe.switch_connection_audited("a", "mongo_c") is False
    # S-6: the active connection is NOT changed on a policy-denied switch.
    assert reg.active == "default"
    audit = _read_audit(tmp_path)
    assert any(r["action"] == "switch_connection" and r["status"] == "denied" for r in audit)


@pytest.mark.asyncio
async def test_s6_empty_allowlist_permits_any_registered(tmp_path):
    reg = _StubRegistry(["mongo_b"])
    pipe = _pipeline_with_registry(
        tmp_path,
        "agent: a\nmode: readonly\n",  # no connections_allow → all allowed
        reg,
    )
    assert await pipe.switch_connection_audited("a", "mongo_b") is True
    assert reg.active == "mongo_b"


# ── 6. _get_executor routes to the ACTIVE connection's executor ──────────────


def test_get_executor_follows_active_connection(tmp_path, monkeypatch):
    _patch_mongo_factory(monkeypatch)
    _write_policy(tmp_path, "agent: default-agent\nmode: readonly\n")

    conns_json = json.dumps(
        {"pg": {"type": "postgres", "dsn": "postgres://u:p@h/app", "database": "app"}}
    )
    monkeypatch.setenv("GUARDMCP_CONNECTIONS", conns_json)
    _mcp, _rest, ctx = build(_settings(tmp_path))
    pipe = ctx.pipeline

    # Default → MongoExecutor.
    assert isinstance(pipe._get_executor(), MongoExecutor)
    # Switch to pg → adapter for that connection.
    assert pipe.switch_connection("pg") is True
    assert isinstance(pipe._get_executor(), CapabilityExecutorAdapter)
    assert pipe._get_executor() is ctx.registry.get("pg").executor
    # Switch back.
    assert pipe.switch_connection("default") is True
    assert isinstance(pipe._get_executor(), MongoExecutor)


# ── 7. Per-connection options flow to ConnectionEntry.options ────────────────


def test_per_connection_options_flow_to_entry(tmp_path):
    reg = ConnectionRegistry()  # direct injection — no client_factory needed
    preg = _build_plugin_registry()
    conns = {
        "analytics": ConnectionConfig(
            type="postgres",
            dsn="postgres://u:p@h/db",
            database="db",
            options={"min_size": 2, "max_size": 8, "ssl": True, "schema": "rpt"},
        )
    }
    register_sql_connections(reg, preg, conns)
    entry = reg.get("analytics")
    assert entry.options == {"min_size": 2, "max_size": 8, "ssl": True, "schema": "rpt"}
    # Options are a COPY, not the same object as the config's options dict.
    assert entry.options is not conns["analytics"].options


# ── 8. ContextVar isolation between copied contexts ──────────────────────────


def test_contextvar_isolation_between_contexts(tmp_path, monkeypatch):
    _patch_mongo_factory(monkeypatch)
    _write_policy(tmp_path, "agent: default-agent\nmode: readonly\n")
    settings = _settings(
        tmp_path,
        extra_connections={"a": "mongodb://a:27017", "b": "mongodb://b:27017"},
    )
    _mcp, _rest, ctx = build(settings)
    registry = ctx.registry

    observed: dict[str, str] = {}

    def _run(switch_to: str, key: str):
        reset_active()
        registry.switch(switch_to)
        observed[key] = registry.active_name()

    ctx_a = contextvars.copy_context()
    ctx_b = contextvars.copy_context()
    ctx_a.run(_run, "a", "ctx_a")
    ctx_b.run(_run, "b", "ctx_b")

    # Each copied context saw only its own switch — no cross-leak.
    assert observed["ctx_a"] == "a"
    assert observed["ctx_b"] == "b"
    # The outer (test) context is unaffected by the inner switches.
    assert registry.active_name() == "default"


# ── 9. registry.manifests() without instantiation / drivers ──────────────────


def test_plugin_manifests_without_instantiation():
    preg: PluginRegistry = _build_plugin_registry()
    manifests = preg.manifests()
    assert {"mongodb", "postgres", "mysql"} <= set(manifests)
    for name in ("mongodb", "postgres", "mysql"):
        m = manifests[name]
        assert m["name"] == name
        assert "api_version" in m
        assert "supported" in m
        assert isinstance(m["supported"], list)
    # Postgres manifest excludes aggregate (capability read from the class only).
    assert "aggregate" not in manifests["postgres"]["supported"]
    assert "aggregate" in manifests["mongodb"]["supported"]


# ── 10. UNSUPPORTED_CAPABILITY path ──────────────────────────────────────────


def test_unsupported_capability_flagged_for_active_sql_connection(tmp_path, monkeypatch):
    _patch_mongo_factory(monkeypatch)
    _write_policy(tmp_path, "agent: default-agent\nmode: readonly\n")
    conns_json = json.dumps(
        {"pg": {"type": "postgres", "dsn": "postgres://u:p@h/app", "database": "app"}}
    )
    monkeypatch.setenv("GUARDMCP_CONNECTIONS", conns_json)
    _mcp, _rest, ctx = build(_settings(tmp_path))
    pipe = ctx.pipeline

    # On the default (mongo) connection AGGREGATE is supported → no objection.
    assert _capability_check(pipe, Action.AGGREGATE) is None

    # Switch to postgres, whose plugin.supported excludes AGGREGATE.
    assert pipe.switch_connection("pg") is True
    pg_plugin = ctx.registry.get("pg").plugin
    assert ACTION_TO_CAPABILITY[Action.AGGREGATE] not in pg_plugin.supported

    unsupported = _capability_check(pipe, Action.AGGREGATE)
    assert unsupported is not None
    # The error envelope names the capability and the backend.
    assert "aggregate" in unsupported.lower()
    assert "postgres" in unsupported.lower()

    # A capability the postgres plugin DOES support is not flagged.
    assert Capability.READ in pg_plugin.supported
    assert _capability_check(pipe, Action.FIND) is None
