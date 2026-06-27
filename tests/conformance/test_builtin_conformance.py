"""Conformance tests for the three builtin GuardMCP plugins.

These prove both (a) the reusable conformance kit works and (b) every shipped
builtin honours the DatabasePlugin contract. No live database and no optional
drivers (asyncpg/aiomysql) are required: plugins are instantiated WITHOUT
connect(), and all checks are static.
"""

from __future__ import annotations

import pytest

from guardmcp.conformance import (
    assert_plugin_conformant,
    check_plugin_conformance,
)
from guardmcp.core.interfaces.capability import Capability, CapabilityRequest
from guardmcp.core.interfaces.errors import GuardValidationError
from guardmcp.plugins.mongodb.plugin import MongoPlugin
from guardmcp.plugins.mysql.plugin import MySQLPlugin
from guardmcp.plugins.postgres.plugin import PostgresPlugin

# (plugin factory, expects_identifier_validation)
_BUILTINS = [
    pytest.param(MongoPlugin, False, id="mongodb"),
    pytest.param(PostgresPlugin, True, id="postgres"),
    pytest.param(MySQLPlugin, True, id="mysql"),
]

# SQL-style plugins additionally undergo a focused injection check.
_SQL_BUILTINS = [
    pytest.param(PostgresPlugin, id="postgres"),
    pytest.param(MySQLPlugin, id="mysql"),
]


@pytest.mark.parametrize("plugin_cls,expects_ident", _BUILTINS)
def test_builtin_is_conformant(plugin_cls, expects_ident):
    plugin = plugin_cls()
    # Should not raise; conveys the full failure list if it does.
    assert_plugin_conformant(plugin, expects_identifier_validation=expects_ident)


@pytest.mark.parametrize("plugin_cls,expects_ident", _BUILTINS)
def test_builtin_check_returns_empty(plugin_cls, expects_ident):
    plugin = plugin_cls()
    assert check_plugin_conformance(plugin, expects_identifier_validation=expects_ident) == []


@pytest.mark.parametrize("plugin_cls", _SQL_BUILTINS)
def test_sql_plugin_rejects_injection_identifier(plugin_cls):
    """SQL-style plugins must reject an injection-style resource identifier."""
    plugin = plugin_cls()
    req = CapabilityRequest(capability=Capability.READ, resource="x; DROP TABLE y")
    with pytest.raises(GuardValidationError):
        plugin.validate_request(req)


def test_non_conformant_plugin_is_detected():
    """A deliberately broken plugin must produce failures (kit is meaningful)."""

    class _Broken:  # not even a DatabasePlugin
        name = ""

    failures = check_plugin_conformance(_Broken())  # type: ignore[arg-type]
    assert failures, "expected the kit to flag a non-DatabasePlugin"
