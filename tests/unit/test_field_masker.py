from guardmcp.core.masking.masker import MASK_VALUE, FieldMasker


def test_masks_specified_fields():
    masker = FieldMasker(["email", "password"])
    result = masker.mask({"name": "Alice", "email": "a@b.com", "password": "secret"})
    assert result["name"] == "Alice"
    assert result["email"] == MASK_VALUE
    assert result["password"] == MASK_VALUE


def test_no_fields_returns_doc_unchanged():
    masker = FieldMasker([])
    doc = {"name": "Alice", "email": "a@b.com"}
    assert masker.mask(doc) == doc


def test_mask_result_handles_list():
    masker = FieldMasker(["email"])
    docs = [{"name": "Alice", "email": "a@b.com"}, {"name": "Bob", "email": "b@c.com"}]
    result = masker.mask_result(docs)
    assert all(d["email"] == MASK_VALUE for d in result)
    assert result[0]["name"] == "Alice"


def test_mask_result_handles_dict():
    masker = FieldMasker(["ssn"])
    result = masker.mask_result({"name": "Alice", "ssn": "123-45-6789"})
    assert result["ssn"] == MASK_VALUE


def test_mask_result_handles_scalar():
    masker = FieldMasker(["email"])
    assert masker.mask_result(42) == 42
