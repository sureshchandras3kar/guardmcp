"""Smoke tests for wiring non-MongoDB connections into the registry without a
live database (instantiation/adapter only — no connect())."""

from guardmcp.__main__ import _build_plugin_registry, register_sql_connections
from guardmcp.config import ConnectionConfig
from guardmcp.core.registry.adapter import CapabilityExecutorAdapter
from guardmcp.core.registry.connections import ConnectionRegistry
from guardmcp.plugins.postgres.plugin import PostgresPlugin


def test_plugin_registry_has_builtins():
    preg = _build_plugin_registry()
    names = set(preg.names())
    assert {"mongodb", "postgres", "mysql"} <= names


def test_register_sql_connection_creates_adapter_unconnected():
    reg = ConnectionRegistry()  # no client_factory needed — we inject directly
    preg = _build_plugin_registry()
    conns = {
        "analytics": ConnectionConfig(type="postgres", dsn="postgres://u:p@h/db", database="db")
    }
    register_sql_connections(reg, preg, conns)

    entry = reg.get("analytics")
    assert entry is not None
    assert isinstance(entry.executor, CapabilityExecutorAdapter)
    assert isinstance(entry.plugin, PostgresPlugin)
    # Plugin is instantiated but NOT connected (no live DB in CI).
    assert entry.plugin._pool is None
    assert entry.database == "db"


def test_register_sql_connection_stores_options_on_entry():
    reg = ConnectionRegistry()
    preg = _build_plugin_registry()
    conns = {
        "analytics": ConnectionConfig(
            type="postgres",
            dsn="postgres://u:p@h/db",
            database="db",
            options={"min_size": 1, "max_size": 10, "ssl": True},
        )
    }
    register_sql_connections(reg, preg, conns)

    entry = reg.get("analytics")
    assert entry is not None
    # #7: per-connection options are carried to the entry for a later connect().
    assert entry.options == {"min_size": 1, "max_size": 10, "ssl": True}


def test_register_sql_connection_skips_mongodb_type():
    reg = ConnectionRegistry()
    preg = _build_plugin_registry()
    conns = {"m": ConnectionConfig(type="mongodb", dsn="mongodb://h/db", database="db")}
    register_sql_connections(reg, preg, conns)
    # mongodb-typed entries are handled by the existing Mongo path, not here.
    assert reg.get("m") is None
