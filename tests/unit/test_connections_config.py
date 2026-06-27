import json

from guardmcp.config import ConnectionConfig, Settings


def test_connections_parses_from_json_env(monkeypatch):
    payload = {
        "analytics": {
            "type": "postgres",
            "dsn": "postgres://u:p@host/appdb",
            "database": "appdb",
        },
        "reporting": {"type": "mysql", "dsn": "mysql://host/rep", "database": "rep"},
    }
    monkeypatch.setenv("GUARDMCP_CONNECTIONS", json.dumps(payload))
    s = Settings()
    assert set(s.connections) == {"analytics", "reporting"}
    assert isinstance(s.connections["analytics"], ConnectionConfig)
    assert s.connections["analytics"].type == "postgres"
    assert s.connections["analytics"].dsn == "postgres://u:p@host/appdb"
    assert s.connections["reporting"].type == "mysql"


def test_connections_default_empty_and_mongo_path_intact(monkeypatch):
    monkeypatch.delenv("GUARDMCP_CONNECTIONS", raising=False)
    s = Settings()
    assert s.connections == {}
    # Backward-compatible defaults still present.
    assert s.mongodb_uri == "mongodb://localhost:27017"
    assert s.mongodb_database == "guardmcp"


def test_connection_config_type_defaults_to_mongodb():
    c = ConnectionConfig(dsn="x")
    assert c.type == "mongodb"
    assert c.database == ""
    # #7: options defaults to an empty dict.
    assert c.options == {}


def test_connection_config_parses_options(monkeypatch):
    payload = {
        "analytics": {
            "type": "postgres",
            "dsn": "postgres://u:p@host/appdb",
            "database": "app",
            "options": {"min_size": 1, "max_size": 10, "ssl": True},
        }
    }
    monkeypatch.setenv("GUARDMCP_CONNECTIONS", json.dumps(payload))
    s = Settings()
    opts = s.connections["analytics"].options
    assert opts == {"min_size": 1, "max_size": 10, "ssl": True}
