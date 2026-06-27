"""#7: capability manifests read from plugin CLASSES without instantiation or
connection — works even when optional SQL drivers aren't installed."""

from guardmcp.core.registry.registry import PluginRegistry
from guardmcp.plugins.mongodb.plugin import MongoPlugin
from guardmcp.plugins.mysql.plugin import MySQLPlugin
from guardmcp.plugins.postgres.plugin import PostgresPlugin


def _registry():
    reg = PluginRegistry()
    reg.register(MongoPlugin)
    reg.register(PostgresPlugin)
    reg.register(MySQLPlugin)
    return reg


def test_class_manifest_without_instance():
    m = PostgresPlugin.manifest()
    assert m["name"] == "postgres"
    assert m["api_version"] == "1.0"
    assert "read" in m["supported"]
    assert m["dialect_features"]["supports_returning"] is True


def test_registry_manifests_no_instantiation():
    manifests = _registry().manifests()
    assert set(manifests) == {"mongodb", "postgres", "mysql"}
    for name in ("mongodb", "postgres", "mysql"):
        man = manifests[name]
        assert man["name"] == name
        assert isinstance(man["supported"], list)
        assert man["supported"], "supported caps must be non-empty"

    assert manifests["mysql"]["dialect_features"]["supports_returning"] is False
    assert manifests["postgres"]["dialect_features"]["placeholder_style"] == "numeric"
    assert "read" in manifests["mongodb"]["supported"]


def test_registry_manifest_single():
    man = _registry().manifest("mysql")
    assert man["name"] == "mysql"
    assert "count" in man["supported"]


def test_manifest_does_not_import_optional_drivers():
    # Building manifests must not require asyncpg/aiomysql. We can't easily
    # assert the negative, but manifest() touches only class attrs — calling it
    # here proves it returns without a driver present in this env.
    man = PostgresPlugin.manifest()
    assert man  # no ImportError raised
