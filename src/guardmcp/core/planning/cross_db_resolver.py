from __future__ import annotations

from collections.abc import Callable

from .cross_db import SAMPLE_CAP, match_cross_db
from .models import CrossDbEdge


class CrossDatabaseResolver:
    def __init__(self, guard, get_plugin: Callable[[], object | None]) -> None:
        self._guard = guard
        self._get_plugin = get_plugin

    async def edges(self, agent: str, databases: list[str]) -> list[CrossDbEdge]:
        inventory: dict[tuple[str, str], set[str]] = {}
        for db in databases:
            try:
                cols = await self._guard.discover_collections(agent, database=db)
            except Exception:
                continue
            for col in cols:
                try:
                    desc = await self._guard.describe_collection(agent, col, database=db)
                except Exception:
                    desc = None
                fields = (desc or {}).get("fields", {})
                names = {f for f, t in fields.items() if t != "masked"}
                if names:
                    inventory[(db, col)] = names

        async def sampler(db: str, col: str, field: str) -> list:
            plugin = self._get_plugin()
            if plugin is None:
                return []
            try:
                return await plugin.sample_field_values(col, field, database=db, cap=SAMPLE_CAP)
            except Exception:
                return []

        return await match_cross_db(inventory, sampler)
