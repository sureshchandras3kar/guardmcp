from __future__ import annotations

from collections.abc import Callable

from .cross_db import (
    SAMPLE_CAP,
    align_by_identifier_role,
    boost_by_roles,
    match_cross_db,
    merge_edges,
)
from .models import CrossDbEdge


class CrossDatabaseResolver:
    def __init__(self, guard, get_plugin: Callable[[], object | None]) -> None:
        self._guard = guard
        self._get_plugin = get_plugin

    async def edges(self, agent: str, databases: list[str]) -> list[CrossDbEdge]:
        inventory: dict[tuple[str, str], set[str]] = {}
        semantics_by_loc: dict[tuple[str, str], dict[str, dict]] = {}
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
                if not desc:
                    continue
                fields = desc.get("fields", {})
                names = {f for f, t in fields.items() if t != "masked"}
                if names:
                    inventory[(db, col)] = names
                masked = set(desc.get("masked_fields", []))
                sem = desc.get("semantics", {})
                loc_sem = {
                    f: {"role": s.get("role"), "references": s.get("references")}
                    for f, s in sem.items()
                    if f not in masked and s.get("role") != "pii"
                }
                if loc_sem:
                    semantics_by_loc[(db, col)] = loc_sem

        async def sampler(db: str, col: str, field: str) -> list:
            plugin = self._get_plugin()
            if plugin is None:
                return []
            try:
                return await plugin.sample_field_values(col, field, database=db, cap=SAMPLE_CAP)
            except Exception:
                return []

        v1 = await match_cross_db(inventory, sampler)
        boosted = boost_by_roles(v1, semantics_by_loc)
        aligned = await align_by_identifier_role(semantics_by_loc, sampler)
        return merge_edges(boosted, aligned)
