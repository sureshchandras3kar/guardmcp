from guardmcp.core.policy.models import CollectionPolicy, DatabaseScope, Policy


def _pol(**kw):
    return Policy(agent="claude", **kw)


def test_backcompat_no_database_config_uses_flat():
    p = _pol(collections=CollectionPolicy(allow=["user"]), mask_fields=["email"])
    assert p.database_permitted(None) is True
    assert p.database_permitted("anydb") is True  # no databases_allow => not enforced
    sc = p.scope_for(None)
    assert sc.collections.allow == ["user"]
    assert p.mask_fields_for("user") == ["email"]


def test_databases_allow_denies_unlisted():
    p = _pol(databases_allow=["db1"])
    assert p.database_permitted("db1") is True
    assert p.database_permitted("db2") is False


def test_scope_for_uses_per_database_block():
    p = _pol(
        databases_allow=["db1", "db2"],
        databases={
            "db1": DatabaseScope(collections=CollectionPolicy(allow=["a"]), mask_fields=["x"]),
            "db2": DatabaseScope(collections=CollectionPolicy(allow=["b"])),
        },
    )
    assert p.scope_for("db1").collections.allow == ["a"]
    assert p.mask_fields_for("a", database="db1") == ["x"]
    assert p.scope_for("db2").collections.allow == ["b"]


def test_scope_for_falls_back_to_default_block():
    p = Policy(
        agent="claude",
        databases_allow=["db1", "dbx"],
        databases={"db1": DatabaseScope(collections=CollectionPolicy(allow=["a"]))},
        **{
            "default": DatabaseScope(
                collections=CollectionPolicy(allow=["z"]), mask_fields=["m"]
            )
        },
    )
    # dbx has no explicit block -> default
    assert p.scope_for("dbx").collections.allow == ["z"]
    assert p.mask_fields_for("anything", database="dbx") == ["m"]
    # db1 explicit block still wins alongside default fallback
    assert p.scope_for("db1").collections.allow == ["a"]


def test_block_empty_piece_falls_back_to_flat():
    p = _pol(
        collections=CollectionPolicy(allow=["flat"]),
        mask_fields=["fm"],
        databases_allow=["db1"],
        databases={"db1": DatabaseScope(fields_allow=["only"])},  # no collections/mask in block
    )
    sc = p.scope_for("db1")
    assert sc.collections.allow == ["flat"]  # fell back
    assert sc.fields_allow == ["only"]  # from block
    assert p.mask_fields_for("x", database="db1") == ["fm"]  # fell back


def test_none_database_permitted_even_with_allow_list():
    p = _pol(databases_allow=["db1"])
    assert p.database_permitted(None) is True
    assert p.database_permitted("db1") is True
    assert p.database_permitted("other") is False
