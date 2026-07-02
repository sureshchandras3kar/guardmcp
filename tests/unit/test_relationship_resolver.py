import pytest

from guardmcp.core.planning.relationships import RelationshipResolver


class _Plugin:
    def __init__(self, edges):
        self._edges = edges
        self.calls = 0

    async def relationships(self, resources):
        self.calls += 1
        return self._edges


@pytest.mark.asyncio
async def test_graph_builds_nodes_and_edges():
    edges = [{"from_resource": "project", "from_field": "user_id", "to_resource": "user",
              "to_field": "_id", "kind": "naming", "confidence": 0.5, "evidence": "x"}]
    r = RelationshipResolver(lambda: _Plugin(edges))
    g = await r.graph(["user", "project"])
    assert set(g.nodes) == {"user", "project"}
    assert len(g.edges) == 1
    assert g.cached is False


@pytest.mark.asyncio
async def test_graph_filters_edges_to_allowed():
    edges = [{"from_resource": "project", "from_field": "secret_id", "to_resource": "secrets",
              "to_field": "_id", "kind": "naming", "confidence": 0.5, "evidence": "x"}]
    r = RelationshipResolver(lambda: _Plugin(edges))
    g = await r.graph(["project"])  # 'secrets' not allowed
    assert g.edges == []


@pytest.mark.asyncio
async def test_cache_hit_marks_cached_and_skips_plugin():
    plugin = _Plugin([])
    r = RelationshipResolver(lambda: plugin)
    await r.graph(["user"])
    g2 = await r.graph(["user"])
    assert g2.cached is True
    assert plugin.calls == 1


@pytest.mark.asyncio
async def test_force_and_invalidate_refetch():
    plugin = _Plugin([])
    r = RelationshipResolver(lambda: plugin)
    await r.graph(["user"])
    await r.graph(["user"], force=True)
    assert plugin.calls == 2
    r.invalidate()
    await r.graph(["user"])
    assert plugin.calls == 3


@pytest.mark.asyncio
async def test_no_plugin_returns_empty_graph():
    r = RelationshipResolver(lambda: None)
    g = await r.graph(["user"])
    assert g.edges == []
    assert g.nodes == ["user"]


@pytest.mark.asyncio
async def test_expired_entry_refetches():
    plugin = _Plugin([])
    now = {"t": 0.0}
    r = RelationshipResolver(lambda: plugin, ttl_seconds=100, clock=lambda: now["t"])
    await r.graph(["user"])
    now["t"] = 50.0
    g_hit = await r.graph(["user"])
    assert g_hit.cached is True and plugin.calls == 1
    now["t"] = 250.0  # past TTL
    g_miss = await r.graph(["user"])
    assert g_miss.cached is False and plugin.calls == 2


@pytest.mark.asyncio
async def test_malformed_edge_is_skipped_not_raised():
    bad = [{"from_resource": "user", "to_resource": "user"}]  # missing required fields
    r = RelationshipResolver(lambda: _Plugin(bad))
    g = await r.graph(["user"])
    assert g.edges == []
