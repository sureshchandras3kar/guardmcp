from guardmcp.core.planning.models import Relationship, RelationshipGraph
from guardmcp.core.planning.relationships import rank_by_centrality


def _rel(a, b, kind="fk"):
    return Relationship(
        from_resource=a, from_field="id", to_resource=b, to_field="id",
        kind=kind, confidence=0.9, evidence="test",
    )


def _graph(nodes, edges):
    return RelationshipGraph(nodes=nodes, edges=edges, generated_at="2026-01-01T00:00:00Z")


def test_ranks_by_edge_degree_descending():
    # "order" touches both edges (degree 2); "user"/"product" touch one each
    # (degree 1, tied -> alphabetical); "review" touches none (degree 0).
    g = _graph(
        ["user", "order", "product", "review"],
        [_rel("user", "order"), _rel("order", "product")],
    )
    ranked = rank_by_centrality(g)
    assert ranked[0] == "order"
    assert ranked[1:3] == ["product", "user"]  # tied at degree 1, alphabetical
    assert ranked[3] == "review"  # degree 0, ranked last


def test_ties_broken_alphabetically_for_determinism():
    g = _graph(["zebra", "apple"], [])
    ranked = rank_by_centrality(g)
    assert ranked == ["apple", "zebra"]


def test_top_n_caps_result():
    g = _graph(["a", "b", "c", "d"], [_rel("a", "b")])
    ranked = rank_by_centrality(g, top_n=2)
    assert len(ranked) == 2
    assert set(ranked) == {"a", "b"}  # the only nodes with any edges


def test_empty_graph_returns_empty():
    g = _graph([], [])
    assert rank_by_centrality(g) == []
