from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

from .models import CrossDbEdge, CrossDbEndpoint

_ID_NAME_RE = re.compile(r"(^_id$|_id$|Id$)")
OVERLAP_MIN = 0.3
SAMPLE_CAP = 100


def cross_db_candidates(
    inventory: dict[tuple[str, str], set[str]],
) -> list[tuple[str, tuple[str, str], tuple[str, str]]]:
    """Pairwise candidates: an id-shaped field name present in collections that
    live in >=2 different databases. Deterministic order."""
    by_field: dict[str, list[tuple[str, str]]] = {}
    for (db, coll), fields in inventory.items():
        for f in fields:
            if _ID_NAME_RE.search(f):
                by_field.setdefault(f, []).append((db, coll))
    out: list[tuple[str, tuple[str, str], tuple[str, str]]] = []
    for field, locs in by_field.items():
        locs_sorted = sorted(locs)
        for i in range(len(locs_sorted)):
            for j in range(i + 1, len(locs_sorted)):
                a, b = locs_sorted[i], locs_sorted[j]
                if a[0] != b[0]:  # different databases only
                    out.append((field, a, b))
    out.sort(key=lambda c: (c[0], c[1], c[2]))
    return out


async def match_cross_db(
    inventory: dict[tuple[str, str], set[str]],
    sample_values: Callable[[str, str, str], Awaitable[list]],
) -> list[CrossDbEdge]:
    edges: list[CrossDbEdge] = []
    for field, (dba, ca), (dbb, cb) in cross_db_candidates(inventory):
        va = set(await sample_values(dba, ca, field))
        vb = set(await sample_values(dbb, cb, field))
        denom = min(len(va), len(vb))
        ratio = (len(va & vb) / denom) if denom else 0.0
        if ratio >= OVERLAP_MIN:
            kind, conf = "value_overlap", round(min(0.9, 0.5 + 0.4 * ratio), 4)
            ev = (
                f"id-shaped name '{field}' shared across '{dba}' and '{dbb}'; "
                f"value overlap {ratio:.2f}"
            )
        else:
            kind, conf = "shared_name", 0.5
            ev = (
                f"id-shaped name '{field}' shared across '{dba}' and '{dbb}'; "
                "low value overlap"
            )
        edges.append(
            CrossDbEdge(
                **{"from": CrossDbEndpoint(database=dba, collection=ca, field=field)},
                to=CrossDbEndpoint(database=dbb, collection=cb, field=field),
                kind=kind, confidence=conf, overlap_ratio=ratio, evidence=ev,
            )
        )
    return edges
