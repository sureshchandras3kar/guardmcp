"""Deterministic relationship inference from field names + indexes (Mongo)."""
from __future__ import annotations

import re

from ...core.planning.planner import indexed_fields

_FK_RE = re.compile(r"^(?P<name>.+?)_id$|^(?P<name2>.+?)Id$")


def _target_of(field: str) -> str | None:
    if field == "_id":
        return None
    m = _FK_RE.match(field)
    if not m:
        return None
    return m.group("name") or m.group("name2")


def _matches_resource(target: str, resource: str) -> bool:
    t = target.lower()
    r = resource.lower()
    return r == t or r == t + "s" or (r.endswith("s") and r[:-1] == t)


def infer_relationships(
    resources: list[str],
    schemas: dict[str, dict],
    indexes_by_resource: dict[str, list[dict]],
) -> list[dict]:
    edges: list[dict] = []
    resource_set = set(resources)
    for r in resources:
        fields = schemas.get(r, {})
        indexed = indexed_fields(indexes_by_resource.get(r, []))
        for field in fields:
            target = _target_of(field)
            if target is None:
                continue
            for t in resource_set:
                if t == r or not _matches_resource(target, t):
                    continue
                is_indexed = field in indexed
                edges.append(
                    {
                        "from_resource": r,
                        "from_field": field,
                        "to_resource": t,
                        "to_field": "_id",
                        "kind": "index" if is_indexed else "naming",
                        "confidence": 0.75 if is_indexed else 0.5,
                        "evidence": (
                            f"field '{field}' on '{r}' "
                            + ("is indexed and " if is_indexed else "")
                            + f"matches resource '{t}' by naming convention"
                        ),
                    }
                )
    edges.sort(key=lambda e: (e["from_resource"], e["from_field"], e["to_resource"]))
    return edges
