"""
Unit tests for the PostgreSQL DatabasePlugin (P4).

No live PostgreSQL: translation is pure and unit-tested; execution is tested
against a fake pool/connection. asyncpg is NOT required to run these tests.
"""

from __future__ import annotations

import pytest

from guardmcp.core.interfaces.capability import Capability, CapabilityRequest
from guardmcp.core.interfaces.errors import GuardValidationError
from guardmcp.core.interfaces.plugin import DatabasePlugin
from guardmcp.plugins.postgres import translate as t
from guardmcp.plugins.postgres.plugin import PostgresPlugin

# ── plugin contract ──────────────────────────────────────────────────────────


def test_is_database_plugin_instance():
    p = PostgresPlugin()
    assert isinstance(p, DatabasePlugin)
    assert p.name == "postgres"
    assert p.api_version == "1.0"


def test_aggregate_and_ddl_not_supported():
    p = PostgresPlugin()
    assert Capability.AGGREGATE not in p.supported
    assert Capability.DDL_CREATE not in p.supported
    assert Capability.DDL_DESTROY not in p.supported
    assert Capability.READ in p.supported


def test_module_imports_without_asyncpg():
    # The import below must succeed even though asyncpg is not installed
    # (it is imported lazily inside connect()).
    import importlib

    mod = importlib.import_module("guardmcp.plugins.postgres.plugin")
    assert mod.PostgresPlugin is PostgresPlugin


# ── pure translation: the core value ─────────────────────────────────────────


def test_read_with_filter_and_operator():
    req = CapabilityRequest(
        capability=Capability.READ,
        resource="users",
        filter={"status": "active", "age": {"$gt": 30}},
    )
    res = t.translate(req)
    assert res.sql == ("SELECT * FROM users WHERE status = $1 AND age > $2")
    assert res.args == ["active", 30]
    # parameter numbers are sequential starting at $1
    assert "$1" in res.sql and "$2" in res.sql


def test_read_tuple_unpacking():
    req = CapabilityRequest(capability=Capability.READ, resource="t")
    sql, args = t.translate(req)
    assert sql == "SELECT * FROM t"
    assert args == []


def test_read_with_projection_limit_offset():
    req = CapabilityRequest(
        capability=Capability.READ,
        resource="public.users",
        projection={"id": 1, "name": 1},
        limit=10,
        skip=5,
    )
    res = t.translate(req)
    assert res.sql == "SELECT id, name FROM public.users LIMIT $1 OFFSET $2"
    assert res.args == [10, 5]


@pytest.mark.parametrize(
    "resource,column",
    [
        ("users; DROP TABLE x", None),
        ("users", "a; --"),
        ("1bad", None),
        ("a.b.c", None),
    ],
)
def test_identifier_injection_rejected(resource, column):
    filt = {column: 1} if column else None
    req = CapabilityRequest(capability=Capability.READ, resource=resource, filter=filt)
    with pytest.raises(GuardValidationError):
        t.translate(req)


def test_value_with_sql_metachars_is_parameterized():
    danger = "' OR 1=1 --"
    req = CapabilityRequest(capability=Capability.READ, resource="users", filter={"name": danger})
    res = t.translate(req)
    # The dangerous string lives ONLY in args, never in the SQL text.
    assert danger in res.args
    assert danger not in res.sql
    assert res.sql == "SELECT * FROM users WHERE name = $1"


def test_count_translation():
    req = CapabilityRequest(capability=Capability.COUNT, resource="orders", filter={"paid": True})
    res = t.translate(req)
    assert res.sql == "SELECT count(*) FROM orders WHERE paid = $1"
    assert res.args == [True]


def test_schema_uses_information_schema():
    req = CapabilityRequest(capability=Capability.SCHEMA, resource="users")
    res = t.translate(req)
    assert "information_schema.columns" in res.sql
    assert "table_name = $1" in res.sql
    assert res.args == ["users"]


def test_schema_with_schema_option():
    req = CapabilityRequest(
        capability=Capability.SCHEMA, resource="users", options={"schema": "app"}
    )
    res = t.translate(req)
    assert "table_schema = $2" in res.sql
    assert res.args == ["users", "app"]


def test_list_resources_default_public():
    req = CapabilityRequest(capability=Capability.LIST_RESOURCES)
    res = t.translate(req)
    assert "information_schema.tables" in res.sql
    assert res.args == ["public"]


def test_indexes_translation():
    req = CapabilityRequest(capability=Capability.INDEXES, resource="users")
    res = t.translate(req)
    assert "pg_indexes" in res.sql
    assert res.args == ["users"]


def test_list_databases_translation():
    req = CapabilityRequest(capability=Capability.LIST_DATABASES)
    res = t.translate(req)
    assert "pg_database" in res.sql
    assert res.args == []


def test_explain_prefixes_read():
    req = CapabilityRequest(capability=Capability.EXPLAIN, resource="users", filter={"id": 1})
    res = t.translate(req)
    assert res.sql.startswith("EXPLAIN SELECT")
    assert res.args == [1]


def test_write_one_insert_column_order():
    req = CapabilityRequest(
        capability=Capability.WRITE_ONE,
        resource="users",
        documents=[{"name": "alice", "age": 30}],
    )
    res = t.translate(req)
    assert res.sql == ("INSERT INTO users (name, age) VALUES ($1, $2) RETURNING *")
    assert res.args == ["alice", 30]


def test_write_many_multi_row_insert():
    req = CapabilityRequest(
        capability=Capability.WRITE_MANY,
        resource="users",
        documents=[{"name": "a"}, {"name": "b"}],
    )
    res = t.translate(req)
    assert res.sql == ("INSERT INTO users (name) VALUES ($1), ($2) RETURNING *")
    assert res.args == ["a", "b"]


def test_write_one_update_when_filter_and_update():
    req = CapabilityRequest(
        capability=Capability.WRITE_ONE,
        resource="users",
        filter={"id": 1},
        update={"$set": {"name": "bob"}},
    )
    res = t.translate(req)
    assert res.sql == "UPDATE users SET name = $1 WHERE id = $2 RETURNING *"
    assert res.args == ["bob", 1]


def test_delete_many_empty_filter_allowed():
    req = CapabilityRequest(capability=Capability.DELETE_MANY, resource="t")
    res = t.translate(req)
    assert res.sql == "DELETE FROM t"
    assert res.args == []


def test_delete_with_filter_parameterized():
    req = CapabilityRequest(capability=Capability.DELETE_MANY, resource="t", filter={"id": 5})
    res = t.translate(req)
    assert res.sql == "DELETE FROM t WHERE id = $1"
    assert res.args == [5]


def test_delete_one_requires_filter():
    req = CapabilityRequest(capability=Capability.DELETE_ONE, resource="t")
    with pytest.raises(GuardValidationError):
        t.translate(req)


def test_delete_one_bounds_to_single_row():
    req = CapabilityRequest(capability=Capability.DELETE_ONE, resource="t", filter={"id": 5})
    res = t.translate(req)
    assert "ctid IN" in res.sql
    assert "LIMIT 1" in res.sql
    assert res.args == [5]


def test_in_operator_uses_any():
    req = CapabilityRequest(
        capability=Capability.READ,
        resource="t",
        filter={"id": {"$in": [1, 2, 3]}},
    )
    res = t.translate(req)
    assert res.sql == "SELECT * FROM t WHERE id = ANY($1)"
    assert res.args == [[1, 2, 3]]


def test_unknown_operator_rejected():
    req = CapabilityRequest(
        capability=Capability.READ,
        resource="t",
        filter={"name": {"$regex": "x"}},
    )
    with pytest.raises(GuardValidationError):
        t.translate(req)


async def test_ddl_create_via_execute_path_rejected():
    p = PostgresPlugin(pool=_FakePool([]))
    req = CapabilityRequest(capability=Capability.DDL_CREATE, resource="t")
    with pytest.raises(GuardValidationError):
        # validate_request passes (DDL_CREATE has no unsafe construct here), but
        # translate() refuses DDL.
        await p.execute(req)


# ── fake pool / conn for execution tests ──────────────────────────────────────


class _FakeConn:
    def __init__(self, rows, status="OK"):
        self._rows = rows
        self._status = status
        self.calls: list[tuple[str, tuple]] = []

    async def fetch(self, sql, *args):
        self.calls.append((sql, args))
        return self._rows

    async def execute(self, sql, *args):
        self.calls.append((sql, args))
        return self._status


class _Acquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


class _FakePool:
    def __init__(self, rows, status="OK"):
        self.conn = _FakeConn(rows, status)

    def acquire(self):
        return _Acquire(self.conn)

    def close(self):
        return None


# ── execution against the fake pool ───────────────────────────────────────────


async def test_execute_read_returns_rows():
    rows = [{"id": 1, "name": "alice"}, {"id": 2, "name": "bob"}]
    pool = _FakePool(rows)
    p = PostgresPlugin(pool=pool)
    req = CapabilityRequest(capability=Capability.READ, resource="users", filter={"id": {"$gt": 0}})
    result = await p.execute(req)
    assert result.rows == rows
    # the parameterized SQL was what ran
    sql, args = pool.conn.calls[0]
    assert sql == "SELECT * FROM users WHERE id > $1"
    assert args == (0,)


async def test_execute_validates_before_touching_pool():
    pool = _FakePool([])
    p = PostgresPlugin(pool=pool)
    req = CapabilityRequest(capability=Capability.READ, resource="users; DROP TABLE x")
    with pytest.raises(GuardValidationError):
        await p.execute(req)
    # never reached the connection
    assert pool.conn.calls == []


async def test_execute_count_sets_scalar():
    pool = _FakePool([{"count": 7}])
    p = PostgresPlugin(pool=pool)
    req = CapabilityRequest(capability=Capability.COUNT, resource="t")
    result = await p.execute(req)
    assert result.scalar == 7


async def test_execute_insert_reports_affected():
    pool = _FakePool([{"id": 1, "name": "alice"}])
    p = PostgresPlugin(pool=pool)
    req = CapabilityRequest(
        capability=Capability.WRITE_ONE,
        resource="users",
        documents=[{"name": "alice"}],
    )
    result = await p.execute(req)
    assert result.affected == 1
    assert result.rows == [{"id": 1, "name": "alice"}]


async def test_schema_introspection_shape():
    rows = [
        {"column_name": "id", "data_type": "integer"},
        {"column_name": "name", "data_type": "text"},
    ]
    p = PostgresPlugin(pool=_FakePool(rows))
    out = await p.schema("users")
    assert out == {"fields": {"id": "integer", "name": "text"}}


async def test_list_resources_introspection():
    rows = [{"table_name": "users"}, {"table_name": "orders"}]
    p = PostgresPlugin(pool=_FakePool(rows))
    assert await p.list_resources() == ["users", "orders"]


async def test_health_true_on_success():
    p = PostgresPlugin(pool=_FakePool([{"?column?": 1}]))
    assert await p.health() is True


async def test_health_false_without_pool():
    p = PostgresPlugin()
    assert await p.health() is False


# ── validate_request ──────────────────────────────────────────────────────────


def test_validate_request_rejects_raw_sql_option():
    p = PostgresPlugin()
    req = CapabilityRequest(
        capability=Capability.READ,
        resource="t",
        options={"raw_sql": "SELECT 1"},
    )
    with pytest.raises(GuardValidationError):
        p.validate_request(req)


def test_validate_request_rejects_bad_identifier():
    p = PostgresPlugin()
    req = CapabilityRequest(capability=Capability.READ, resource="bad; --")
    with pytest.raises(GuardValidationError):
        p.validate_request(req)


def test_validate_request_passes_clean():
    p = PostgresPlugin()
    req = CapabilityRequest(
        capability=Capability.READ,
        resource="users",
        filter={"status": "active", "age": {"$gte": 18}},
        projection={"id": 1},
    )
    # should not raise
    p.validate_request(req)


def test_cross_resource_refs_default_empty():
    p = PostgresPlugin()
    req = CapabilityRequest(capability=Capability.READ, resource="t")
    assert p.cross_resource_refs(req) == set()


def test_cross_resource_refs_from_joins_option():
    p = PostgresPlugin()
    req = CapabilityRequest(
        capability=Capability.READ,
        resource="t",
        options={"joins": ["orders", "payments"]},
    )
    assert p.cross_resource_refs(req) == {"orders", "payments"}


# ── affected-count from status tag (no RETURNING) ────────────────────────────


def test_affected_from_status_parsing():
    from guardmcp.plugins.postgres.plugin import _affected_from_status

    assert _affected_from_status("DELETE 5") == 5
    assert _affected_from_status("UPDATE 3") == 3
    assert _affected_from_status("INSERT 0 1") == 1
    assert _affected_from_status("") == 0
    assert _affected_from_status(None) == 0


async def test_delete_reports_affected_via_status():
    """DELETE has no RETURNING → affected must come from the status tag, not fetch()."""
    from guardmcp.core.interfaces.capability import Capability, CapabilityRequest
    from guardmcp.plugins.postgres.plugin import PostgresPlugin

    class _Conn:
        async def fetch(self, sql, *args):
            return []  # asyncpg returns [] for a no-RETURNING DELETE

        async def execute(self, sql, *args):
            return "DELETE 7"  # the real affected count lives here

    class _Acq:
        async def __aenter__(self):
            return _Conn()

        async def __aexit__(self, *a):
            return False

    class _Pool:
        def acquire(self):
            return _Acq()

    plugin = PostgresPlugin(pool=_Pool())
    res = await plugin.execute(
        CapabilityRequest(
            capability=Capability.DELETE_MANY, resource="users", filter={"status": "old"}
        )
    )
    assert res.affected == 7
