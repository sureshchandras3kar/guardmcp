import pytest

from guardmcp.core.registry.connections import ConnectionRegistry


class _FakeClient:
    """Backend-agnostic stub satisfying the ClosableClient protocol."""

    def __init__(self, uri, database, **opts):
        self.uri = uri
        self.database = database
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _factory(uri, database, *, min_pool_size, max_pool_size):
    return _FakeClient(uri, database, min_pool_size=min_pool_size, max_pool_size=max_pool_size)


def _reg() -> ConnectionRegistry:
    return ConnectionRegistry(client_factory=_factory)


def test_register_and_list():
    reg = _reg()
    reg.register("prod", "mongodb://prod:27017", "mydb")
    reg.register("staging", "mongodb://staging:27017", "mydb")
    assert "prod" in reg.list_names()
    assert "staging" in reg.list_names()
    reg.close_all()


def test_default_active_is_default():
    reg = _reg()
    assert reg.active_name() == "default"


def test_switch_to_registered():
    reg = _reg()
    reg.register("staging", "mongodb://staging:27017", "mydb")
    ok = reg.switch("staging")
    assert ok is True
    assert reg.active_name() == "staging"
    reg.close_all()


def test_switch_to_unknown_returns_false():
    reg = _reg()
    ok = reg.switch("nonexistent")
    assert ok is False


def test_get_returns_entry():
    reg = _reg()
    reg.register("prod", "mongodb://prod:27017", "mydb")
    entry = reg.get("prod")
    assert entry is not None
    assert entry.database == "mydb"
    reg.close_all()


def test_get_unknown_returns_none():
    reg = _reg()
    assert reg.get("missing") is None


def test_register_without_factory_raises():
    reg = ConnectionRegistry()  # no factory
    with pytest.raises(RuntimeError):
        reg.register("x", "uri", "db")


def test_close_all_closes_clients():
    reg = _reg()
    reg.register("prod", "mongodb://prod:27017", "mydb")
    entry = reg.get("prod")
    reg.close_all()
    assert entry.client.closed is True
