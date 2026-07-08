import pytest

from guardmcp.core.planning.cross_db import compose_transitive_paths
from guardmcp.core.planning.models import CrossDbEdge, CrossDbEndpoint


def _edge(db_a, col_a, field_a, db_b, col_b, field_b, kind="value_overlap", confidence=0.8):
    return CrossDbEdge(
        **{"from": CrossDbEndpoint(database=db_a, collection=col_a, field=field_a)},
        to=CrossDbEndpoint(database=db_b, collection=col_b, field=field_b),
        kind=kind,
        confidence=confidence,
        overlap_ratio=0.5,
        evidence="test",
    )


def test_composes_two_hop_path_from_pairwise_edges():
    # identity.user --account_id-- inventory.resource --sku-- cost.ledger
    e1 = _edge(
        "identity", "user", "account_id", "inventory", "resource", "account_id", confidence=0.9
    )
    e2 = _edge("inventory", "resource", "sku", "cost", "ledger", "sku", confidence=0.7)
    paths = compose_transitive_paths([e1, e2])
    assert len(paths) == 1
    p = paths[0]
    assert set(p.nodes) == {"identity.user", "inventory.resource", "cost.ledger"}
    assert p.nodes[0] != p.nodes[-1]
    assert len(p.edges) == 2
    assert {id(e) for e in p.edges} == {id(e1), id(e2)}
    assert p.confidence == pytest.approx(0.7)  # weakest-link


def test_no_path_when_databases_disjoint():
    e1 = _edge("identity", "user", "account_id", "inventory", "resource", "account_id")
    e2 = _edge("billing", "invoice", "acct", "billing", "account", "acct")
    paths = compose_transitive_paths([e1, e2])
    assert paths == []


def test_does_not_revisit_a_node_no_cycles():
    # a-b, b-a (reverse duplicate-ish edge) must not produce a 2-hop a-b-a path
    e1 = _edge("a", "c1", "f", "b", "c2", "f")
    e2 = _edge("b", "c2", "f", "a", "c1", "f")
    paths = compose_transitive_paths([e1, e2])
    assert paths == []


def test_respects_max_hops():
    e1 = _edge("a", "c1", "f1", "b", "c2", "f2")
    e2 = _edge("b", "c2", "f2", "c", "c3", "f3")
    e3 = _edge("c", "c3", "f3", "d", "c4", "f4")
    paths = compose_transitive_paths([e1, e2, e3], max_hops=2)
    # only 2-hop paths allowed; the 3-hop a->b->c->d chain must be excluded
    assert all(len(p.edges) <= 2 for p in paths)
    assert not any(set(p.nodes) == {"a.c1", "b.c2", "c.c3", "d.c4"} for p in paths)


def test_deterministic_regardless_of_input_edge_order():
    e1 = _edge(
        "identity", "user", "account_id", "inventory", "resource", "account_id", confidence=0.9
    )
    e2 = _edge("inventory", "resource", "sku", "cost", "ledger", "sku", confidence=0.7)
    r1 = compose_transitive_paths([e2, e1])
    r2 = compose_transitive_paths([e1, e2])
    assert [p.model_dump() for p in r1] == [p.model_dump() for p in r2]
