"""
Shared SQL cost normalization for the relational plugins.

Postgres (``EXPLAIN (FORMAT JSON)``) and MySQL (``EXPLAIN FORMAT=JSON``) produce
different JSON shapes, but both are normalized into the SAME backend-neutral
:class:`CostEstimate` here, deferring the coarse LOW/MEDIUM/HIGH/CRITICAL
bucketing to the SHARED ``classify_cost`` heuristic so thresholds stay identical
across Mongo + both SQL backends. NEVER returns the raw plan.

Both EXPLAIN forms used here are PLAN-ONLY (no ``ANALYZE`` / no execution): they
report the planner's row/cost ESTIMATES without running the query.
"""

from __future__ import annotations

from typing import Any

from ...core.interfaces.cost import CostEstimate, classify_cost

# Postgres scan node types that mean "no index / full table scan".
_PG_SEQ_SCANS = {"Seq Scan"}
_PG_INDEX_SCANS = {"Index Scan", "Index Only Scan", "Bitmap Index Scan", "Bitmap Heap Scan"}

# MySQL access_type values: ALL = full table scan; the rest use an index/range.
_MYSQL_SCAN_ACCESS = {"ALL"}
_MYSQL_INDEX_ACCESS = {"ref", "eq_ref", "const", "range", "index", "index_merge", "fulltext"}


def _scan_warning(collection_scan: bool) -> list[str]:
    if collection_scan:
        return [
            "operation performs a full table scan (no index) — consider adding "
            "an index on the filtered column(s)"
        ]
    return []


def normalize_postgres_explain(explain_json: Any) -> CostEstimate:
    """Normalize a Postgres ``EXPLAIN (FORMAT JSON)`` payload → CostEstimate.

    The payload is a list with one element ``{"Plan": {...}}``. We read the top
    Plan node's ``Node Type`` (Seq Scan → scan; Index Scan → index), ``Plan
    Rows`` (estimated rows) and ``Total Cost``.
    """
    plan = _pg_top_plan(explain_json)
    if not isinstance(plan, dict):
        return CostEstimate(warnings=["could not parse postgres explain output"])

    node_type = plan.get("Node Type")
    plan_rows = plan.get("Plan Rows")
    collection_scan = node_type in _PG_SEQ_SCANS
    index_used = node_type in _PG_INDEX_SCANS

    have_signal = collection_scan or index_used
    level = classify_cost(
        estimated_documents=int(plan_rows) if isinstance(plan_rows, (int, float)) else None,
        collection_scan=collection_scan if have_signal else None,
        index_used=index_used if have_signal else None,
    )
    return CostEstimate(
        estimated_documents=int(plan_rows) if isinstance(plan_rows, (int, float)) else None,
        collection_scan=collection_scan if have_signal else None,
        index_used=index_used if have_signal else None,
        estimated_cost=level,
        warnings=_scan_warning(collection_scan),
    )


def _pg_top_plan(explain_json: Any) -> Any:
    payload = explain_json
    if isinstance(payload, list) and payload:
        payload = payload[0]
    if isinstance(payload, dict):
        return payload.get("Plan")
    return None


def normalize_mysql_explain(explain_json: Any) -> CostEstimate:
    """Normalize a MySQL ``EXPLAIN FORMAT=JSON`` payload → CostEstimate.

    Reads ``query_block.table.access_type`` (ALL → scan; ref/eq_ref/range/... →
    index), ``rows_examined_per_scan`` (estimated rows) and ``query_cost``.
    """
    if not isinstance(explain_json, dict):
        return CostEstimate(warnings=["could not parse mysql explain output"])
    qb = explain_json.get("query_block")
    if not isinstance(qb, dict):
        return CostEstimate(warnings=["could not parse mysql explain output"])

    table = _mysql_first_table(qb)
    if not isinstance(table, dict):
        # No table node (e.g. a constant/derived query) — unknown.
        return CostEstimate(warnings=["mysql explain had no table node"])

    access_type = table.get("access_type")
    rows = table.get("rows_examined_per_scan")
    if rows is None:
        rows = table.get("rows_produced_per_join")

    collection_scan = access_type in _MYSQL_SCAN_ACCESS
    index_used = access_type in _MYSQL_INDEX_ACCESS
    have_signal = collection_scan or index_used

    level = classify_cost(
        estimated_documents=int(rows) if isinstance(rows, (int, float)) else None,
        collection_scan=collection_scan if have_signal else None,
        index_used=index_used if have_signal else None,
    )
    return CostEstimate(
        estimated_documents=int(rows) if isinstance(rows, (int, float)) else None,
        collection_scan=collection_scan if have_signal else None,
        index_used=index_used if have_signal else None,
        estimated_cost=level,
        warnings=_scan_warning(collection_scan),
    )


def _mysql_first_table(query_block: dict[str, Any]) -> Any:
    """Locate the primary table node in a MySQL EXPLAIN query_block.

    MySQL nests the table under ``table`` directly, or under ``nested_loop`` /
    ``ordering_operation`` / ``grouping_operation``. Walk a few known wrappers.
    """
    if "table" in query_block:
        return query_block["table"]
    for key in ("ordering_operation", "grouping_operation", "duplicates_removal"):
        inner = query_block.get(key)
        if isinstance(inner, dict):
            found = _mysql_first_table(inner)
            if found is not None:
                return found
    nested = query_block.get("nested_loop")
    if isinstance(nested, list) and nested:
        first = nested[0]
        if isinstance(first, dict) and "table" in first:
            return first["table"]
    return None
