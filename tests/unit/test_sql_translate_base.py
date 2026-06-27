"""Tests for the shared SqlTranslator core with a fake dialect.

These exercise the dialect-agnostic logic ONCE: that a fake dialect produces the
expected SQL, that quote_ident rejects injection, and that the two placeholder
styles ($n vs %s) and $in strategies (ANY(array) vs expanded) differ as intended.
"""

from __future__ import annotations

import pytest

from guardmcp.core.interfaces.capability import Capability, CapabilityRequest
from guardmcp.core.interfaces.errors import GuardValidationError
from guardmcp.plugins.sql import Dialect, SqlTranslator, validate_ident

# ── fake dialects ────────────────────────────────────────────────────────────────


def _catalog(text):
    return lambda req, counter: text


def _make_dialect(
    *,
    name="FakeDB",
    dollar=True,
    backtick=False,
    returning=True,
    array_in=True,
    delete_one="ctid",
):
    def placeholder(n):
        return f"${n}" if dollar else "%s"

    def quote_ident(ident):
        parts = validate_ident(ident)
        if backtick:
            return ".".join(f"`{p}`" for p in parts)
        return ident

    return Dialect(
        name=name,
        placeholder=placeholder,
        quote_ident=quote_ident,
        supports_returning=returning,
        in_uses_array=array_in,
        delete_one_strategy=delete_one,
        schema_sql=_catalog("SCHEMA_SQL"),
        indexes_sql=_catalog("INDEXES_SQL"),
        list_resources_sql=_catalog("LIST_SQL"),
        list_databases_sql=_catalog("DBS_SQL"),
        stats_sql=_catalog("STATS_SQL"),
    )


def _req(cap, **kw):
    return CapabilityRequest(capability=cap, **kw)


# ── identifier validation / injection ──────────────────────────────────────────


@pytest.mark.parametrize(
    "bad",
    [
        "users; DROP TABLE users",
        "users WHERE 1=1",
        "1users",
        "users.col.extra",
        "users-table",
        "",
        "'x'",
    ],
)
def test_quote_ident_rejects_injection(bad):
    d = _make_dialect()
    with pytest.raises(GuardValidationError):
        d.quote_ident(bad)


def test_validate_ident_returns_parts():
    assert validate_ident("users") == ["users"]
    assert validate_ident("public.users") == ["public", "users"]


# ── placeholder styles differ ────────────────────────────────────────────────────


def test_placeholder_styles_differ():
    pg = SqlTranslator(_make_dialect(dollar=True))
    my = SqlTranslator(_make_dialect(dollar=False, backtick=True))
    req = _req(Capability.READ, resource="users", filter={"status": "active"}, limit=5)
    pg_sql, pg_args = pg.translate(req)
    my_sql, my_args = my.translate(req)
    assert pg_sql == "SELECT * FROM users WHERE status = $1 LIMIT $2"
    assert my_sql == "SELECT * FROM `users` WHERE `status` = %s LIMIT %s"
    assert pg_args == ["active", 5]
    assert my_args == ["active", 5]


# ── $in strategies differ ────────────────────────────────────────────────────────


def test_in_array_vs_expanded():
    array = SqlTranslator(_make_dialect(array_in=True))
    expanded = SqlTranslator(_make_dialect(array_in=False, dollar=False))
    req = _req(Capability.READ, resource="t", filter={"id": {"$in": [1, 2, 3]}})
    a_sql, a_args = array.translate(req)
    e_sql, e_args = expanded.translate(req)
    assert a_sql == "SELECT * FROM t WHERE id = ANY($1)"
    assert a_args == [[1, 2, 3]]
    assert e_sql == "SELECT * FROM t WHERE id IN (%s, %s, %s)"
    assert e_args == [1, 2, 3]


def test_in_expanded_rejects_empty():
    expanded = SqlTranslator(_make_dialect(array_in=False))
    with pytest.raises(GuardValidationError):
        expanded.translate(_req(Capability.READ, resource="t", filter={"id": {"$in": []}}))


# ── operators ─────────────────────────────────────────────────────────────────────


def test_operator_set():
    tr = SqlTranslator(_make_dialect())
    req = _req(
        Capability.COUNT,
        resource="t",
        filter={"a": {"$gt": 1}, "b": {"$lte": 2}, "c": {"$ne": 3}},
    )
    sql, args = tr.translate(req)
    assert sql == "SELECT count(*) FROM t WHERE a > $1 AND b <= $2 AND c != $3"
    assert args == [1, 2, 3]


def test_unsupported_operator_rejected():
    tr = SqlTranslator(_make_dialect())
    with pytest.raises(GuardValidationError):
        tr.translate(_req(Capability.READ, resource="t", filter={"a": {"$regex": "x"}}))


# ── RETURNING delta ──────────────────────────────────────────────────────────────


def test_insert_returning_delta():
    with_ret = SqlTranslator(_make_dialect(returning=True))
    no_ret = SqlTranslator(_make_dialect(returning=False))
    req = _req(Capability.WRITE_ONE, resource="t", documents=[{"a": 1}])
    assert with_ret.translate(req).sql.endswith("RETURNING *")
    assert not no_ret.translate(req).sql.endswith("RETURNING *")


# ── DELETE_ONE strategy delta ────────────────────────────────────────────────────


def test_delete_one_ctid_vs_limit():
    ctid = SqlTranslator(_make_dialect(delete_one="ctid"))
    limit = SqlTranslator(_make_dialect(delete_one="limit"))
    req = _req(Capability.DELETE_ONE, resource="t", filter={"id": 5})
    assert ctid.translate(req).sql == (
        "DELETE FROM t WHERE ctid IN (SELECT ctid FROM t WHERE id = $1 LIMIT 1)"
    )
    assert limit.translate(req).sql == "DELETE FROM t WHERE id = $1 LIMIT 1"


def test_delete_one_requires_filter():
    tr = SqlTranslator(_make_dialect())
    with pytest.raises(GuardValidationError):
        tr.translate(_req(Capability.DELETE_ONE, resource="t"))


# ── catalog dispatch + unsupported caps ─────────────────────────────────────────


def test_catalog_dispatch():
    tr = SqlTranslator(_make_dialect())
    assert tr.translate(_req(Capability.SCHEMA, resource="t")).sql == "SCHEMA_SQL"
    assert tr.translate(_req(Capability.INDEXES, resource="t")).sql == "INDEXES_SQL"
    assert tr.translate(_req(Capability.LIST_RESOURCES)).sql == "LIST_SQL"
    assert tr.translate(_req(Capability.LIST_DATABASES)).sql == "DBS_SQL"
    assert tr.translate(_req(Capability.STATS)).sql == "STATS_SQL"


def test_unsupported_capabilities_use_dialect_name():
    tr = SqlTranslator(_make_dialect(name="WidgetDB"))
    with pytest.raises(GuardValidationError, match="AGGREGATE not supported via WidgetDB"):
        tr.translate(_req(Capability.AGGREGATE, resource="t"))
    with pytest.raises(GuardValidationError, match="DDL not supported via WidgetDB"):
        tr.translate(_req(Capability.DDL_CREATE, resource="t"))
