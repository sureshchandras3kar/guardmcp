from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime

from .models import Relationship, RelationshipGraph


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
