"""#10: first-class dotted mask paths — "contact.email" is path-specific while a
bare "email" keeps the historical any-depth behaviour. Mixed lists allowed."""

from guardmcp.core.masking.masker import MASK_VALUE, FieldMasker, ResultTransformer


def _doc():
    return {
        "email": "top@x.com",
        "contact": {"email": "nested@x.com", "phone": "555"},
    }


def test_dotted_path_is_specific():
    masked = FieldMasker(["contact.email"]).mask(_doc())
    assert masked["contact"]["email"] == MASK_VALUE
    # The top-level email is NOT masked by a dotted path.
    assert masked["email"] == "top@x.com"
    assert masked["contact"]["phone"] == "555"


def test_bare_name_masks_any_depth_backcompat():
    masked = FieldMasker(["email"]).mask(_doc())
    assert masked["email"] == MASK_VALUE
    assert masked["contact"]["email"] == MASK_VALUE


def test_mixed_bare_and_dotted():
    masked = FieldMasker(["password", "contact.email"]).mask({**_doc(), "password": "p"})
    assert masked["password"] == MASK_VALUE
    assert masked["contact"]["email"] == MASK_VALUE
    assert masked["email"] == "top@x.com"


def test_transformer_dotted_path_specific():
    t = ResultTransformer(["contact.email"], [])
    out = t.transform_result(_doc())
    assert out["contact"]["email"] == MASK_VALUE
    assert out["email"] == "top@x.com"


def test_transformer_bare_backcompat():
    t = ResultTransformer(["email"], [])
    out = t.transform_result(_doc())
    assert out["email"] == MASK_VALUE
    assert out["contact"]["email"] == MASK_VALUE


def test_per_collection_dict_with_dotted(monkeypatch):
    from guardmcp.core.policy.models import Policy

    p = Policy(
        agent="a",
        mask_fields={"orders": ["contact.email"], "*": ["password"]},
    )
    eff = p.mask_fields_for("orders")
    assert "contact.email" in eff
    assert "password" in eff
    t = p.result_transformer("orders")
    out = t.transform_result({**_doc(), "password": "p"})
    assert out["contact"]["email"] == MASK_VALUE
    assert out["password"] == MASK_VALUE
    assert out["email"] == "top@x.com"
