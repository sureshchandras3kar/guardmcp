from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

from .models import CrossDbEdge, CrossDbEndpoint

_ID_NAME_RE = re.compile(r"(^_id$|_id$|Id$)")
OVERLAP_MIN = 0.3
SAMPLE_CAP = 100

# Signal-3 constants
ALIGN_BASE = 0.75
ROLE_BOOST = 0.15
CONF_CAP = 0.95
_ROLE_PRIMARY = "primary_identifier"
_ROLE_FOREIGN = "foreign_identifier"
_ROLE_TENANT = "tenant_key"


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


def _matches_resource(target: str, collection: str) -> bool:
    """Match a resource name (exact / singular / plural).
    Case-insensitive exact match, or singular/plural forms match."""
    t, c = target.lower(), collection.lower()
    # Exact match
    if t == c:
        return True
    # target singular matches collection plural
    if (t + "s") == c:
        return True
    # target plural matches collection singular
    if t == c.rstrip("s"):
        return True
    # collection singular matches target plural
    return (c + "s") == t


def _primary_field(loc_sem: dict[str, dict]) -> str | None:
    """The primary_identifier field of a collection (prefer '_id')."""
    prims = [f for f, s in loc_sem.items() if s.get("role") == _ROLE_PRIMARY]
    if not prims:
        return None
    return "_id" if "_id" in prims else sorted(prims)[0]


def _endpoint_role(
    semantics_by_loc: dict[tuple[str, str], dict[str, dict]],
    database: str,
    collection: str,
    field: str,
) -> str | None:
    """Look up the role of a field endpoint."""
    return (semantics_by_loc.get((database, collection), {}).get(field) or {}).get("role")


async def align_by_identifier_role(
    semantics_by_loc: dict[tuple[str, str], dict[str, dict]],
    sample_values: Callable[[str, str, str], Awaitable[list]],
) -> list[CrossDbEdge]:
    """Capability B: foreign_identifier.references -> another DB's primary_identifier."""
    edges: list[CrossDbEdge] = []
    fks: list[tuple[str, str, str, str]] = []  # (dbA, collA, field, references)
    for (dba, ca), fields in semantics_by_loc.items():
        for f, s in fields.items():
            if s.get("role") == _ROLE_FOREIGN and s.get("references"):
                fks.append((dba, ca, f, s["references"]))
    fks.sort()
    targets = sorted(semantics_by_loc.keys())
    for dba, ca, f, ref in fks:
        for dbb, cb in targets:
            if dbb == dba or not _matches_resource(ref, cb):
                continue
            pk = _primary_field(semantics_by_loc[(dbb, cb)])
            if pk is None:
                continue
            va = set(await sample_values(dba, ca, f))
            vb = set(await sample_values(dbb, cb, pk))
            denom = min(len(va), len(vb))
            ratio = (len(va & vb) / denom) if denom else 0.0
            conf = round(min(CONF_CAP, ALIGN_BASE + 0.2 * ratio), 4)
            edges.append(
                CrossDbEdge(
                    **{"from": CrossDbEndpoint(database=dba, collection=ca, field=f)},
                    to=CrossDbEndpoint(database=dbb, collection=cb, field=pk),
                    kind="identifier_alignment", confidence=conf, overlap_ratio=ratio,
                    evidence=(
                        f"foreign_identifier '{ca}.{f}' references '{ref}' -> "
                        f"primary key '{dbb}.{cb}.{pk}' (value overlap {ratio:.2f})"
                    ),
                )
            )
    return edges


def boost_by_roles(
    edges: list[CrossDbEdge],
    semantics_by_loc: dict[tuple[str, str], dict[str, dict]],
) -> list[CrossDbEdge]:
    """Capability A: upgrade a v1 edge whose endpoint roles align."""
    out: list[CrossDbEdge] = []
    for e in edges:
        ra = _endpoint_role(
            semantics_by_loc, e.from_.database, e.from_.collection, e.from_.field
        )
        rb = _endpoint_role(semantics_by_loc, e.to.database, e.to.collection, e.to.field)
        pair = {ra, rb}
        aligned = ({_ROLE_FOREIGN, _ROLE_PRIMARY} == pair) or (
            ra == _ROLE_TENANT and rb == _ROLE_TENANT
        )
        if aligned:
            out.append(
                e.model_copy(update={
                    "kind": "identifier_alignment",
                    "confidence": round(min(CONF_CAP, e.confidence + ROLE_BOOST), 4),
                    "evidence": e.evidence + f"; role-aligned ({ra}/{rb})",
                })
            )
        else:
            out.append(e)
    return out


def merge_edges(*edge_lists: list[CrossDbEdge]) -> list[CrossDbEdge]:
    """Concatenate + dedupe by UNORDERED endpoint pair, keeping higher confidence
    (tie → prefer identifier_alignment). Deterministic order."""
    best: dict[frozenset, CrossDbEdge] = {}
    for lst in edge_lists:
        for e in lst:
            key = frozenset({
                (e.from_.database, e.from_.collection, e.from_.field),
                (e.to.database, e.to.collection, e.to.field),
            })
            cur = best.get(key)
            if (
                cur is None
                or e.confidence > cur.confidence
                or (
                    e.confidence == cur.confidence
                    and e.kind == "identifier_alignment" != cur.kind
                )
            ):
                best[key] = e
    return sorted(
        best.values(),
        key=lambda e: (e.from_.database, e.from_.collection, e.from_.field,
                       e.to.database, e.to.collection, e.to.field),
    )
