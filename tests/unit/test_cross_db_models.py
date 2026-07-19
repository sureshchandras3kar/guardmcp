from guardmcp.core.planning.models import CrossDbEdge, CrossDbEndpoint


def test_endpoint_fields():
    e = CrossDbEndpoint(database="identity", collection="user", field="account_id")
    assert (e.database, e.collection, e.field) == ("identity", "user", "account_id")


def test_edge_defaults_and_from_alias():
    edge = CrossDbEdge(
        from_=CrossDbEndpoint(database="identity", collection="user", field="account_id"),
        to=CrossDbEndpoint(database="inventory", collection="resource", field="account_id"),
        kind="shared_name", confidence=0.5,
    )
    assert edge.overlap_ratio is None and edge.evidence == ""
    dumped = edge.model_dump(by_alias=True)
    assert "from" in dumped and dumped["from"]["database"] == "identity"
    assert dumped["to"]["field"] == "account_id"
