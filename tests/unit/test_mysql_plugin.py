"""
Unit tests for the MySQL DatabasePlugin (P5).

No live MySQL: translation is pure and unit-tested; execution is tested against a
fake aiomysql-style pool/connection/cursor. aiomysql is NOT required to run these
tests (it is imported lazily inside connect()).
"""

from __future__ import annotations

from typing import Any

import pytest

from guardmcp.core.interfaces.capability import Capability, CapabilityRequest
from guardmcp.core.interfaces.errors import GuardValidationError
from guardmcp.core.interfaces.plugin import DatabasePlugin
from guardmcp.plugins.mysql import translate as t
from guardmcp.plugins.mysql.plugin import MySQLPlugin

# ── plugin contract ──────────────────────────────────────────────────────────


def test_is_database_plugin_instance():
    p = MySQLPlugin()
    assert isinstance(p, DatabasePlugin)
    assert p.name == "mysql"
    assert p.api_version == "1.0"


def test_aggregate_and_ddl_not_supported():
    p = MySQLPlugin()
    assert Capability.AGGREGATE not in p.supported
    assert Capability.DDL_CREATE not in p.supported
    assert Capability.DDL_DESTROY not in p.supported
    assert Capability.READ in p.supported


def test_module_imports_without_aiomysql():
    # The import below must succeed even though aiomysql is not installed
    # (it is imported lazily inside connect()).
    import importlib

    mod = importlib.import_module("guardmcp.plugins.mysql.plugin")
    assert mod.MySQLPlugin is MySQLPlugin


# ── pure translation: the core value ─────────────────────────────────────────


def test_read_with_filter_and_operator():
    req = CapabilityRequest(
        capability=Capability.READ,
        resource="users",
        filter={"status": "active", "age": {"$gt": 30}},
    )
    res = t.translate(req)
    assert res.sql == ("SELECT * FROM `users` WHERE `status` = %s AND `age` > %s")
    assert res.args == ["active", 30]
    # MySQL placeholders are %s, NOT $1; identifiers are backtick-quoted.
    assert "%s" in res.sql
    assert "$1" not in res.sql
    assert "`users`" in res.sql and "`status`" in res.sql


def test_read_tuple_unpacking():
    req = CapabilityRequest(capability=Capability.READ, resource="t")
    sql, args = t.translate(req)
    assert sql == "SELECT * FROM `t`"
    assert args == []


def test_read_with_projection_limit_offset():
    req = CapabilityRequest(
        capability=Capability.READ,
        resource="app.users",
        projection={"id": 1, "name": 1},
        limit=10,
        skip=5,
    )
    res = t.translate(req)
    assert res.sql == ("SELECT `id`, `name` FROM `app`.`users` LIMIT %s OFFSET %s")
    assert res.args == [10, 5]


@pytest.mark.parametrize(
    "resource,column",
    [
        ("users; DROP TABLE x", None),
        ("users", "a; --"),
        ("1bad", None),
        ("a.b.c", None),
        ("users`", None),
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
    assert res.sql == "SELECT * FROM `users` WHERE `name` = %s"


def test_count_translation():
    req = CapabilityRequest(capability=Capability.COUNT, resource="orders", filter={"paid": True})
    res = t.translate(req)
    assert res.sql == "SELECT count(*) FROM `orders` WHERE `paid` = %s"
    assert res.args == [True]


def test_schema_uses_information_schema_and_database():
    req = CapabilityRequest(capability=Capability.SCHEMA, resource="users")
    res = t.translate(req)
    assert "information_schema.columns" in res.sql
    assert "table_name = %s" in res.sql
    assert "table_schema = DATABASE()" in res.sql
    assert res.args == ["users"]


def test_list_resources_uses_database():
    req = CapabilityRequest(capability=Capability.LIST_RESOURCES)
    res = t.translate(req)
    assert "information_schema.tables" in res.sql
    assert "table_schema = DATABASE()" in res.sql
    assert res.args == []


def test_indexes_uses_show_index():
    req = CapabilityRequest(capability=Capability.INDEXES, resource="users")
    res = t.translate(req)
    assert res.sql == "SHOW INDEX FROM `users`"
    assert res.args == []


def test_list_databases_uses_show_databases():
    req = CapabilityRequest(capability=Capability.LIST_DATABASES)
    res = t.translate(req)
    assert res.sql == "SHOW DATABASES"
    assert res.args == []


def test_stats_translation():
    req = CapabilityRequest(capability=Capability.STATS)
    res = t.translate(req)
    assert "information_schema.tables" in res.sql
    assert "DATABASE()" in res.sql
    assert res.args == []


def test_explain_prefixes_read():
    req = CapabilityRequest(capability=Capability.EXPLAIN, resource="users", filter={"id": 1})
    res = t.translate(req)
    assert res.sql.startswith("EXPLAIN SELECT")
    assert res.args == [1]


def test_write_one_insert_no_returning():
    req = CapabilityRequest(
        capability=Capability.WRITE_ONE,
        resource="users",
        documents=[{"name": "alice", "age": 30}],
    )
    res = t.translate(req)
    assert res.sql == ("INSERT INTO `users` (`name`, `age`) VALUES (%s, %s)")
    assert "RETURNING" not in res.sql
    assert res.args == ["alice", 30]


def test_write_many_multi_row_insert():
    req = CapabilityRequest(
        capability=Capability.WRITE_MANY,
        resource="users",
        documents=[{"name": "a"}, {"name": "b"}],
    )
    res = t.translate(req)
    assert res.sql == ("INSERT INTO `users` (`name`) VALUES (%s), (%s)")
    assert "RETURNING" not in res.sql
    assert res.args == ["a", "b"]


def test_write_one_update_when_filter_and_update():
    req = CapabilityRequest(
        capability=Capability.WRITE_ONE,
        resource="users",
        filter={"id": 1},
        update={"$set": {"name": "bob"}},
    )
    res = t.translate(req)
    assert res.sql == "UPDATE `users` SET `name` = %s WHERE `id` = %s"
    assert "RETURNING" not in res.sql
    assert res.args == ["bob", 1]


def test_delete_many_empty_filter_allowed():
    req = CapabilityRequest(capability=Capability.DELETE_MANY, resource="t")
    res = t.translate(req)
    assert res.sql == "DELETE FROM `t`"
    assert "WHERE" not in res.sql
    assert "LIMIT" not in res.sql
    assert res.args == []


def test_delete_with_filter_parameterized():
    req = CapabilityRequest(capability=Capability.DELETE_MANY, resource="t", filter={"id": 5})
    res = t.translate(req)
    assert res.sql == "DELETE FROM `t` WHERE `id` = %s"
    assert res.args == [5]


def test_delete_one_requires_filter():
    req = CapabilityRequest(capability=Capability.DELETE_ONE, resource="t")
    with pytest.raises(GuardValidationError):
        t.translate(req)


def test_delete_one_bounds_to_single_row_with_limit():
    req = CapabilityRequest(capability=Capability.DELETE_ONE, resource="t", filter={"id": 5})
    res = t.translate(req)
    assert res.sql == "DELETE FROM `t` WHERE `id` = %s LIMIT 1"
    assert res.sql.endswith("LIMIT 1")
    assert res.args == [5]


def test_in_operator_expands_to_n_placeholders():
    req = CapabilityRequest(
        capability=Capability.READ,
        resource="t",
        filter={"id": {"$in": [1, 2, 3]}},
    )
    res = t.translate(req)
    # MySQL has no ANY(array): expand to N %s placeholders.
    assert res.sql == "SELECT * FROM `t` WHERE `id` IN (%s, %s, %s)"
    assert res.args == [1, 2, 3]


def test_unknown_operator_rejected():
    req = CapabilityRequest(
        capability=Capability.READ,
        resource="t",
        filter={"name": {"$regex": "x"}},
    )
    with pytest.raises(GuardValidationError):
        t.translate(req)


async def test_ddl_create_via_execute_path_rejected():
    p = MySQLPlugin(pool=_FakePool([]))
    req = CapabilityRequest(capability=Capability.DDL_CREATE, resource="t")
    with pytest.raises(GuardValidationError):
        # validate_request passes (DDL_CREATE has no unsafe construct here), but
        # translate() refuses DDL.
        await p.execute(req)


# ── fake aiomysql-style pool / conn / cursor for execution tests ──────────────


class _FakeCursor:
    def __init__(self, rows, rowcount=1, lastrowid=0, description=None):
        self._rows = rows
        self.rowcount = rowcount
        self.lastrowid = lastrowid
        self.description = description
        self.calls: list[tuple[str, Any]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, sql, args=None):
        self.calls.append((sql, args))

    async def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


class _Acquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


class _FakePool:
    def __init__(self, rows, rowcount=1, lastrowid=0, description=None):
        self.cursor = _FakeCursor(rows, rowcount, lastrowid, description)
        self.conn = _FakeConn(self.cursor)

    def acquire(self):
        return _Acquire(self.conn)

    def close(self):
        return None


# ── execution against the fake pool ───────────────────────────────────────────


async def test_execute_read_returns_rows():
    rows = [{"id": 1, "name": "alice"}, {"id": 2, "name": "bob"}]
    pool = _FakePool(rows)
    p = MySQLPlugin(pool=pool)
    req = CapabilityRequest(capability=Capability.READ, resource="users", filter={"id": {"$gt": 0}})
    result = await p.execute(req)
    assert result.rows == rows
    # the parameterized SQL was what ran, with %s placeholders
    sql, args = pool.cursor.calls[0]
    assert sql == "SELECT * FROM `users` WHERE `id` > %s"
    assert args == [0]


async def test_execute_maps_tuple_rows_via_description():
    rows = [(1, "alice")]
    pool = _FakePool(rows, description=[("id",), ("name",)])
    p = MySQLPlugin(pool=pool)
    req = CapabilityRequest(capability=Capability.READ, resource="users")
    result = await p.execute(req)
    assert result.rows == [{"id": 1, "name": "alice"}]


async def test_execute_validates_before_touching_pool():
    pool = _FakePool([])
    p = MySQLPlugin(pool=pool)
    req = CapabilityRequest(capability=Capability.READ, resource="users; DROP TABLE x")
    with pytest.raises(GuardValidationError):
        await p.execute(req)
    # never reached the connection
    assert pool.cursor.calls == []


async def test_execute_count_sets_scalar():
    pool = _FakePool([{"count(*)": 7}])
    p = MySQLPlugin(pool=pool)
    req = CapabilityRequest(capability=Capability.COUNT, resource="t")
    result = await p.execute(req)
    assert result.scalar == 7


async def test_execute_insert_reports_affected_and_lastrowid():
    pool = _FakePool([], rowcount=1, lastrowid=42)
    p = MySQLPlugin(pool=pool)
    req = CapabilityRequest(
        capability=Capability.WRITE_ONE,
        resource="users",
        documents=[{"name": "alice"}],
    )
    result = await p.execute(req)
    assert result.affected == 1
    assert result.meta.get("lastrowid") == 42
    # MySQL has no RETURNING: no rows come back from an insert.
    assert result.rows == []


async def test_schema_introspection_shape():
    rows = [
        {"column_name": "id", "data_type": "int"},
        {"column_name": "name", "data_type": "varchar"},
    ]
    p = MySQLPlugin(pool=_FakePool(rows))
    out = await p.schema("users")
    assert out == {"fields": {"id": "int", "name": "varchar"}}


async def test_list_resources_introspection():
    rows = [{"table_name": "users"}, {"table_name": "orders"}]
    p = MySQLPlugin(pool=_FakePool(rows))
    assert await p.list_resources() == ["users", "orders"]


async def test_health_true_on_success():
    p = MySQLPlugin(pool=_FakePool([(1,)]))
    assert await p.health() is True


async def test_health_false_without_pool():
    p = MySQLPlugin()
    assert await p.health() is False


# ── validate_request ──────────────────────────────────────────────────────────


def test_validate_request_rejects_raw_sql_option():
    p = MySQLPlugin()
    req = CapabilityRequest(
        capability=Capability.READ,
        resource="t",
        options={"raw_sql": "SELECT 1"},
    )
    with pytest.raises(GuardValidationError):
        p.validate_request(req)


def test_validate_request_rejects_bad_identifier():
    p = MySQLPlugin()
    req = CapabilityRequest(capability=Capability.READ, resource="bad; --")
    with pytest.raises(GuardValidationError):
        p.validate_request(req)


def test_validate_request_passes_clean():
    p = MySQLPlugin()
    req = CapabilityRequest(
        capability=Capability.READ,
        resource="users",
        filter={"status": "active", "age": {"$gte": 18}},
        projection={"id": 1},
    )
    # should not raise
    p.validate_request(req)


def test_cross_resource_refs_default_empty():
    p = MySQLPlugin()
    req = CapabilityRequest(capability=Capability.READ, resource="t")
    assert p.cross_resource_refs(req) == set()


def test_cross_resource_refs_from_joins_option():
    p = MySQLPlugin()
    req = CapabilityRequest(
        capability=Capability.READ,
        resource="t",
        options={"joins": ["orders", "payments"]},
    )
    assert p.cross_resource_refs(req) == {"orders", "payments"}
