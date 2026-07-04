from guardmcp.server.tools._common import ToolContext, _resolve_database


def _ctx(active=None):
    box = {"db": active}
    return ToolContext(
        get_pipeline=lambda: None, get_agent=lambda: "claude", get_settings=lambda: None,
        get_active_database=lambda: box["db"],
        set_active_database=lambda v: box.__setitem__("db", v),
    )


def test_resolve_prefers_per_call():
    ctx = _ctx(active="sessiondb")
    assert _resolve_database(ctx, "calldb") == "calldb"


def test_resolve_falls_back_to_active():
    ctx = _ctx(active="sessiondb")
    assert _resolve_database(ctx, None) == "sessiondb"


def test_resolve_none_when_no_active():
    ctx = _ctx(active=None)
    assert _resolve_database(ctx, None) is None


def test_set_active_database_roundtrips():
    ctx = _ctx()
    ctx.set_active_database("db2")
    assert ctx.get_active_database() == "db2"
