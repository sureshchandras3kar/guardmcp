"""
MongoDB-specific validation / guard logic.

Moved out of core/validation.py in P3b so core stays database-agnostic. These
helpers are Mongo-shaped (operator/stage names, pipeline structure) and raise
ToolError from the MCP tool layer.

Fix 2: has_dangerous_operators()  — blocks $where/$function/$accumulator injection
Fix 6: sanitize_mongo_error()     — never leak internal MongoDB error detail
Fix 7: validate_pipeline_stages() — block $out/$merge/$function in aggregations
"""

from typing import Any

from mcp.server.fastmcp.exceptions import ToolError

# ── Fix 2 ─────────────────────────────────────────────────────────────────────
# JavaScript-execution operators enable arbitrary code on the MongoDB server.
# $out/$merge are write operators that bypass GuardMCP's write-mode check.
# Other $-prefixed comparison operators ($gt, $in, etc.) are allowed.
_BANNED_OPERATORS: frozenset[str] = frozenset(
    {
        "$where",  # JS execution
        "$function",  # JS execution (aggregation)
        "$accumulator",  # JS execution (aggregation)
        "$out",  # writes to a collection
        "$merge",  # writes / upserts to a collection
    }
)

_BANNED_PIPELINE_STAGES: frozenset[str] = frozenset(
    {
        "$out",
        "$merge",
        "$function",
        "$accumulator",
    }
)


def has_dangerous_operators(value: Any, /) -> bool:
    """True if value contains any banned operator key at any nesting depth."""
    if isinstance(value, dict):
        return any(k in _BANNED_OPERATORS for k in value) or any(
            has_dangerous_operators(v) for v in value.values()
        )
    if isinstance(value, list):
        return any(has_dangerous_operators(item) for item in value)
    return False


# ── C1: cross-collection access via aggregation ────────────────────────────────
# $lookup / $graphLookup / $unionWith can read a DIFFERENT collection via their
# `from`/`coll` field. Without extraction, an agent restricted to "customers" can
# read "payroll" through {"$lookup": {"from": "payroll", ...}}. We extract every
# referenced collection (including nested $facet sub-pipelines and $lookup
# sub-pipelines) so the policy engine can authorize each one.

_FOREIGN_COLLECTION_KEYS: frozenset[str] = frozenset({"from", "coll"})


def extract_pipeline_collections(pipeline: Any) -> set[str]:
    """
    Return every foreign collection name referenced by an aggregation pipeline,
    recursively (handles $lookup, $graphLookup, $unionWith, $facet sub-pipelines,
    and $lookup `pipeline` sub-pipelines).
    """
    found: set[str] = set()

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                # $unionWith string shorthand: {"$unionWith": "other_coll"} — the
                # collection name is the VALUE of the operator key, not under from/coll.
                if (
                    k == "$unionWith"
                    and isinstance(v, str)
                    or k in _FOREIGN_COLLECTION_KEYS
                    and isinstance(v, str)
                ):
                    found.add(v)
                else:
                    _walk(v)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(pipeline)
    return found


# ── C2: masked-field leakage via aggregation aliasing ──────────────────────────
# FieldMasker masks by KEY name. An aggregation can rename a masked field
# ({"$group": {"_id": "$email"}}) or project it under a new name
# ({"$project": {"x": "$email"}}), moving the sensitive VALUE to an unmasked key.
# We detect any field-path reference ("$email" / "$email.sub") to a masked field
# anywhere in the pipeline and reject — masking is not rename-safe.


def find_masked_field_references(pipeline: Any, mask_fields: list[str]) -> set[str]:
    """
    Return the set of masked field names referenced as aggregation field paths
    ("$field" or "$field.sub") anywhere in the pipeline. A non-empty result means
    the pipeline could expose a masked value under a different key.
    """
    if not mask_fields:
        return set()
    masked = set(mask_fields)
    hits: set[str] = set()

    def _check_str(s: str) -> None:
        if not s.startswith("$"):
            return
        # strip leading "$" and any operator prefix like "$$"
        path = s.lstrip("$")
        head = path.split(".", 1)[0]
        if head in masked:
            hits.add(head)

    def _walk(node: Any) -> None:
        if isinstance(node, str):
            _check_str(node)
        elif isinstance(node, dict):
            for v in node.values():
                _walk(v)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(pipeline)
    return hits


def validate_filter(value: Any, param_name: str = "filter") -> None:
    """
    Fix 2: raise ToolError if filter is not a dict or contains dangerous operators.
    Fix 8: error message states what was wrong so AI can self-correct.
    """
    if not isinstance(value, dict):
        raise ToolError(f"{param_name} must be a JSON object, got {type(value).__name__}.")
    if has_dangerous_operators(value):
        raise ToolError(
            f"{param_name} contains a disallowed operator. "
            f"Banned operators: {sorted(_BANNED_OPERATORS)}. "
            "Use plain comparison fields or safe operators like $gt, $in, $and, $or."
        )


# ── Fix 7 ─────────────────────────────────────────────────────────────────────


def validate_pipeline_stages(pipeline: list[Any]) -> None:
    """
    Fix 7: reject pipelines containing write or JS-execution stages.
    Fix 8: error names the bad stage and lists what is permitted.
    """
    allowed_stages = {
        "$match",
        "$group",
        "$project",
        "$sort",
        "$limit",
        "$skip",
        "$unwind",
        "$lookup",
        "$count",
        "$facet",
        "$bucket",
        "$bucketAuto",
        "$sortByCount",
        "$addFields",
        "$replaceRoot",
        "$replaceWith",
        "$sample",
        "$geoNear",
        "$graphLookup",
        "$unionWith",
    }
    for i, stage in enumerate(pipeline):
        if not isinstance(stage, dict) or len(stage) != 1:
            raise ToolError(
                f'Pipeline stage {i} must be a single-key object, e.g. {{"$match": {{...}}}}.'
            )
        op = next(iter(stage))
        if op in _BANNED_PIPELINE_STAGES:
            raise ToolError(
                f"Pipeline stage '{op}' is not permitted. Allowed stages: {sorted(allowed_stages)}."
            )
        # CR-3: ENFORCE the allow-list. Previously only the banned set was
        # checked, so $unionWith/$collStats/$indexStats/$documents silently
        # passed. Anything not explicitly allowed is now rejected. Foreign
        # collections in $lookup/$graphLookup/$unionWith are authorized
        # separately by the policy engine (GuardPipeline._guard_aggregation).
        if op not in allowed_stages:
            raise ToolError(
                f"Pipeline stage '{op}' is not on the allow-list. "
                f"Allowed stages: {sorted(allowed_stages)}."
            )
        if has_dangerous_operators(stage[op]):
            raise ToolError(
                f"Pipeline stage '{op}' contains a disallowed operator. "
                f"Banned: {sorted(_BANNED_OPERATORS)}."
            )


# ── Fix 6 ─────────────────────────────────────────────────────────────────────


def sanitize_mongo_error(exc: Exception) -> str:
    """
    Fix 6: return a generic, actionable message instead of raw MongoDB internals.
    The real error is meant to be logged server-side via ctx.error().
    """
    msg = str(exc).lower()
    if "collection" in msg and "not found" in msg:
        return "Collection not found. Use mongodb_list_collections to see available collections."
    if "authentication" in msg or "auth" in msg:
        return "MongoDB authentication failed. Check server configuration."
    if "timeout" in msg or "timed out" in msg:
        return "MongoDB operation timed out. Try a more specific filter or smaller limit."
    if "duplicate" in msg or "e11000" in msg:
        return "Duplicate key error. Document with that key already exists."
    return "Query failed. Check collection name, filter syntax, and parameter types."
