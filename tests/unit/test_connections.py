import pytest

from guardmcp.core.registry.connections import ConnectionRegistry, reset_active


@pytest.fixture(autouse=True)
def _reset_active_connection():
    """_active_connection/_active_databases are module-level ContextVars —
    pytest runs test functions in the same real thread/context (no isolation
    between them), so a switch()/set_active_database() in one test would
    otherwise leak into the next. Mirrors the same fixture in
    test_connection_usecases.py."""
    reset_active()
    yield
    reset_active()


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


# ── Per-connection active database ───────────────────────────────────────────


def test_active_database_defaults_to_none():
    reg = _reg()
    reg.register("prod", "mongodb://prod:27017", "mydb")
    assert reg.get_active_database() is None


def test_set_active_database_stores_on_the_active_connection():
    reg = _reg()
    reg.register("prod", "mongodb://prod:27017", "mydb")
    reg.switch("prod")
    reg.set_active_database("identity")
    assert reg.get_active_database() == "identity"


def test_each_connection_remembers_its_own_active_database_independently():
    reg = _reg()
    reg.register("a", "mongodb://a:27017", "mydb")
    reg.register("b", "mongodb://b:27017", "mydb")

    reg.switch("a")
    reg.set_active_database("identity")

    reg.switch("b")
    assert reg.get_active_database() is None  # "b" never had one set
    reg.set_active_database("inventory")
    assert reg.get_active_database() == "inventory"

    # Switching back to "a" restores ITS remembered database, unaffected by "b".
    reg.switch("a")
    assert reg.get_active_database() == "identity"


def test_set_active_database_with_no_active_entry_is_a_noop():
    reg = _reg()  # "default" never registered -> get_active() is None
    reg.set_active_database("identity")  # must not raise
    assert reg.get_active_database() is None


def test_active_database_isolated_between_contextvar_contexts():
    """Regression: active_database must be a ContextVar (like _active_connection),
    NOT a field on the shared ConnectionEntry — otherwise two concurrent
    sessions on the SAME connection (the common single-connection deployment)
    would leak each other's db_use_database state. Mirrors
    test_contextvar_isolation_between_contexts in test_connection_usecases.py."""
    import contextvars

    reg = _reg()
    reg.register("prod", "mongodb://prod:27017", "mydb")
    reg.switch("prod")  # same connection shared by both simulated sessions below

    observed: dict[str, str | None] = {}

    def _run(db_name, key):
        reg.set_active_database(db_name)
        observed[key] = reg.get_active_database()

    ctx_a = contextvars.copy_context()
    ctx_b = contextvars.copy_context()
    ctx_a.run(_run, "identity", "session_a")
    ctx_b.run(_run, "inventory", "session_b")

    assert observed["session_a"] == "identity"
    assert observed["session_b"] == "inventory"
    # The outer context (never called set_active_database) is unaffected.
    assert reg.get_active_database() is None
