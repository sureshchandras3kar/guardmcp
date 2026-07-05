from __future__ import annotations

import re

from .models import (
    ROLE_ENUM,
    ROLE_FOREIGN,
    ROLE_NONE,
    ROLE_PII,
    ROLE_PRIMARY,
    ROLE_TENANT,
    ROLE_TIMESTAMP,
    FieldSemantics,
    SemanticsInput,
    SemanticsResult,
)

TENANT_FANIN_MIN = 3
ENUM_MAX_DISTINCT = 12
NEAR_UNIQUE_RATIO = 0.95
ENUM_VALUES_CAP = 20

# Generic (product-neutral) name tokens — BOOSTERS only, never required.
_PII_RE = re.compile(
    r"(email|e_mail|ssn|social|phone|mobile|credit|card|passw|secret|token|api_?key)", re.I
)
_SCOPE_RE = re.compile(
    r"(tenant|account|organi[sz]ation|org|customer|workspace|company)", re.I
)
_ID_RE = re.compile(r"(^id$|_id$|Id$|uuid|guid|(^|_)key$)", re.I)
_TIME_RE = re.compile(r"(_at$|_time$|_date$|^created|^updated|^modified|^timestamp)", re.I)
_STATUS_RE = re.compile(r"(status|state|type|kind|level|mode|stage|phase)", re.I)


def _looks_pii(field: str) -> bool:
    return bool(_PII_RE.search(field))


def _unique_single_index_fields(indexes: list[dict]) -> set[str]:
    out: set[str] = set()
    for idx in indexes:
        if not idx.get("unique"):
            continue
        keys = idx.get("key", [])
        if len(keys) == 1:
            pair = keys[0]
            out.add(pair[0] if isinstance(pair, (list, tuple)) else pair)
    return out


class FieldSemanticsAnalyzer:
    def analyze(self, inp: SemanticsInput) -> SemanticsResult:
        masked = set(inp.masked_fields)
        fk_by_field = {e["from_field"]: e for e in inp.edges if "from_field" in e}
        unique_single = _unique_single_index_fields(inp.indexes)
        out: dict[str, FieldSemantics] = {}

        for field, ftype in inp.fields.items():
            # Masked → pii by NAME ONLY. Never inspect stats/values.
            if field in masked:
                out[field] = FieldSemantics(
                    role=ROLE_PII, confidence=1.0, evidence="policy-masked field", pii=True
                )
                continue

            pii = _looks_pii(field)
            role, conf, ev, refs, values = ROLE_NONE, 0.0, "", None, None
            stat = inp.field_stats.get(field)

            if field == "_id":
                role, conf, ev = ROLE_PRIMARY, 1.0, "document identity field '_id'"
            elif field in fk_by_field:
                edge = fk_by_field[field]
                refs = edge.get("to_resource")
                fin = inp.fan_in.get(field, 0)
                if fin >= TENANT_FANIN_MIN:
                    role = ROLE_TENANT
                    conf = min(0.9, 0.5 + 0.08 * fin)
                    ev = f"foreign identifier referenced across {fin} collections"
                    if _SCOPE_RE.search(field):
                        conf = min(0.95, conf + 0.1)
                        ev += " + generic scope-token name"
                else:
                    role = ROLE_FOREIGN
                    conf = float(edge.get("confidence", 0.5))
                    ev = f"foreign-key edge to '{refs}'"
            elif field in unique_single and stat and _near_unique(stat):
                role, conf = ROLE_PRIMARY, 0.8
                ev = "single-field unique index, near-unique in sample"
                if _ID_RE.search(field):
                    conf = min(0.9, conf + 0.1)
                    ev += " + id-like name"
            elif ftype in ("date", "datetime"):
                role, conf, ev = ROLE_TIMESTAMP, 0.9, "date/datetime type"
            elif _TIME_RE.search(field):
                role, conf, ev = ROLE_TIMESTAMP, 0.6, "time-like name"
            elif ftype == "string" and _is_enum(stat):
                role = ROLE_ENUM
                conf = 0.7
                values = list(stat.sample_values or [])[:ENUM_VALUES_CAP]
                ev = f"low-cardinality string ({stat.distinct_count} distinct in sample)"
                if _STATUS_RE.search(field):
                    conf = min(0.85, conf + 0.1)
                    ev += " + status-like name"

            out[field] = FieldSemantics(
                role=role, confidence=round(conf, 4), evidence=ev,
                references=refs, values=values, pii=pii,
            )
        return SemanticsResult(fields=out)


def _near_unique(stat) -> bool:
    if stat is None or stat.distinct_count is None or stat.count <= 0:
        return False
    return (stat.distinct_count / stat.count) >= NEAR_UNIQUE_RATIO


def _is_enum(stat) -> bool:
    if stat is None or stat.distinct_count is None or stat.count <= 0:
        return False
    return 0 < stat.distinct_count <= ENUM_MAX_DISTINCT and stat.distinct_count < stat.count
