from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime

from .models import Relationship, RelationshipGraph

DEFAULT_CENTRALITY_TOP_N = 3


def rank_by_centrality(graph: RelationshipGraph, top_n: int | None = None) -> list[str]:
    """Rank graph.nodes by edge degree (in + out), descending; ties broken
    alphabetically for determinism. Nodes with zero edges still appear (rank
    last). Used to cap expensive per-collection lookups (e.g. field semantics)
    to the most-connected collections first. `top_n=None` returns every node."""
    degree: dict[str, int] = dict.fromkeys(graph.nodes, 0)
    for e in graph.edges:
        if e.from_resource in degree:
            degree[e.from_resource] += 1
        if e.to_resource in degree:
            degree[e.to_resource] += 1
    ranked = sorted(degree, key=lambda n: (-degree[n], n))
    return ranked[:top_n] if top_n is not None else ranked


class RelationshipResolver:
    def __init__(self, get_plugin: Callable[[], object | None], *, ttl_seconds: int = 300,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._get_plugin = get_plugin
        self._ttl = ttl_seconds
        self._clock = clock
        self._cache: dict[tuple[str, ...], tuple[float, RelationshipGraph]] = {}

    def invalidate(self) -> None:
        self._cache.clear()

    async def graph(
        self, allowed_resources: list[str], *, force: bool = False
    ) -> RelationshipGraph:
        key = tuple(sorted(allowed_resources))
        now = self._clock()
        if not force and key in self._cache:
            ts, cached = self._cache[key]
            if now - ts < self._ttl:
                return cached.model_copy(update={"cached": True})

        allowed = set(allowed_resources)
        edges: list[Relationship] = []
        plugin = self._get_plugin()
        if plugin is not None:
            try:
                raw = await plugin.relationships(list(allowed_resources))
            except Exception:
                raw = []
            for e in raw:
                if e.get("from_resource") in allowed and e.get("to_resource") in allowed:
                    try:
                        edges.append(Relationship(**e))
                    except Exception:
                        continue
        graph = RelationshipGraph(
            nodes=list(allowed_resources),
            edges=edges,
            generated_at=datetime.now(UTC).isoformat(),
            cached=False,
        )
        self._cache[key] = (now, graph)
        return graph
