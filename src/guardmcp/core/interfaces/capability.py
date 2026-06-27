from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from ..models.domain import Action


class Capability(str, Enum):
    READ = "read"
    COUNT = "count"
    AGGREGATE = "aggregate"
    WRITE_ONE = "write_one"
    WRITE_MANY = "write_many"
    DELETE_ONE = "delete_one"
    DELETE_MANY = "delete_many"
    SCHEMA = "schema"
    INDEXES = "indexes"
    EXPLAIN = "explain"
    # Read-only/introspection: derive a normalized CostEstimate for an op via the
    # backend's native explain. NOT a write capability. Distinct from EXPLAIN
    # because EXPLAIN returns a (Mongo-shaped) plan dict, while ESTIMATE returns a
    # backend-neutral, normalized CostEstimate and NEVER the raw plan.
    ESTIMATE = "estimate"
    LIST_RESOURCES = "list_resources"
    LIST_DATABASES = "list_databases"
    STATS = "stats"
    DDL_CREATE = "ddl_create"
    DDL_DESTROY = "ddl_destroy"


WRITE_CAPS = frozenset(
    {
        Capability.WRITE_ONE,
        Capability.WRITE_MANY,
        Capability.DELETE_ONE,
        Capability.DELETE_MANY,
        Capability.DDL_CREATE,
        Capability.DDL_DESTROY,
    }
)


class CapabilityRequest(BaseModel):
    capability: Capability
    resource: str = ""
    filter: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Portable predicate dialect that each plugin compiles to its native "
            "query language. The supported, bounded operator set is "
            "$gt/$gte/$lt/$lte/$ne/$in plus bare-equality ({field: value}). The "
            "MongoDB-operator shape is a DOCUMENTED PORTABLE CONTRACT, not an "
            "accident: SQL plugins translate it to parameterized WHERE clauses, "
            "Mongo passes it through. Anything outside this set is rejected by "
            "the plugin's validator."
        ),
    )
    projection: dict[str, Any] | None = None
    documents: list[dict[str, Any]] | None = None
    update: dict[str, Any] | None = None
    pipeline: list[dict[str, Any]] | None = None
    options: dict[str, Any] = Field(default_factory=dict)
    limit: int | None = None
    skip: int | None = None
    # ── Risk #1: the concrete operation name (e.g. "insert_one" / "update_one").
    # First-class field that disambiguates the ambiguous write capabilities
    # (WRITE_ONE → insert vs update, WRITE_MANY → insert_many vs update_many)
    # WITHOUT smuggling the action through `options`. When set, it is AUTHORITATIVE
    # for resolving a concrete backend operation; when None, plugins fall back to
    # CAPABILITY_TO_ACTION (which defaults the ambiguous write caps to insert).
    action: str | None = None
    # ── Risk #2: additive request surface beyond the MongoDB shape. All optional
    # and default None → fully backward compatible. Plugins that do not support a
    # given field ignore it or raise GuardValidationError.
    sort: dict[str, int] | None = None  # e.g. {"created_at": -1}
    returning: list[str] | None = None  # SQL RETURNING / projection of written rows
    joins: list[dict[str, Any]] | None = None  # structured join specs (relational)
    tx_id: str | None = None  # transaction handle (see DatabasePlugin txn seam)
    # ── #2 seam (v2 groundwork, NOT wired): structured predicate AST.
    # Shape: a leaf {"field", "op", "value"} or a node {"and": [...]} / {"or": [...]}.
    # When present, plugins SHOULD compile it natively; `filter` (the Mongo-operator
    # dialect) remains the v1 portable contract. If BOTH are present, predicate WINS.
    # Compilation is NOT wired in v1 — see compile_predicate_to_filter() which can
    # already LOWER a simple predicate AST to the existing Mongo-operator filter.
    predicate: dict[str, Any] | None = Field(
        default=None,
        description=(
            "structured predicate AST (v2): {field, op, value} / {and:[...]} / "
            "{or:[...]}. When present, plugins SHOULD compile it natively; `filter` "
            "(the Mongo-operator dialect) remains the v1 portable contract. Both "
            "present → predicate wins."
        ),
    )


class CapabilityResult(BaseModel):
    rows: list[dict[str, Any]] = Field(default_factory=list)
    affected: int | None = None
    meta: dict[str, Any] = Field(default_factory=dict)
    scalar: int | None = None


# Map the existing MongoDB-flavored Action enum to the generic, backend-neutral
# Capability enum. Plugins reason in terms of Capability; the legacy pipeline
# still speaks Action. This is the bridge between the two.
ACTION_TO_CAPABILITY: dict[Action, Capability] = {
    Action.FIND: Capability.READ,
    Action.COUNT: Capability.COUNT,
    Action.AGGREGATE: Capability.AGGREGATE,
    Action.EXPLAIN: Capability.EXPLAIN,
    Action.COLLECTION_SCHEMA: Capability.SCHEMA,
    Action.COLLECTION_INDEXES: Capability.INDEXES,
    Action.LIST_DATABASES: Capability.LIST_DATABASES,
    Action.DB_STATS: Capability.STATS,
    Action.INSERT_ONE: Capability.WRITE_ONE,
    Action.INSERT_MANY: Capability.WRITE_MANY,
    Action.UPDATE_ONE: Capability.WRITE_ONE,
    Action.UPDATE_MANY: Capability.WRITE_MANY,
    Action.DELETE_ONE: Capability.DELETE_ONE,
    Action.DELETE_MANY: Capability.DELETE_MANY,
    Action.DROP: Capability.DDL_DESTROY,
    Action.CREATE_INDEX: Capability.DDL_CREATE,
    Action.DROP_INDEX: Capability.DDL_DESTROY,
}


# Reverse direction (Risk #1): the concrete operation name a capability resolves
# to when the caller does NOT pin an explicit `req.action`. Only the UNAMBIGUOUS
# capabilities are mapped here. The ambiguous write capabilities (WRITE_ONE,
# WRITE_MANY, DDL_CREATE, DDL_DESTROY) deliberately default to a single concrete
# action — for those, `req.action` is AUTHORITATIVE and should be set by callers
# that need the non-default operation (e.g. update vs insert, drop_index vs drop).
CAPABILITY_TO_ACTION: dict[Capability, str] = {
    Capability.READ: Action.FIND.value,
    Capability.COUNT: Action.COUNT.value,
    Capability.AGGREGATE: Action.AGGREGATE.value,
    Capability.EXPLAIN: Action.EXPLAIN.value,
    Capability.SCHEMA: Action.COLLECTION_SCHEMA.value,
    Capability.INDEXES: Action.COLLECTION_INDEXES.value,
    Capability.LIST_DATABASES: Action.LIST_DATABASES.value,
    Capability.STATS: Action.DB_STATS.value,
    Capability.DELETE_ONE: Action.DELETE_ONE.value,
    Capability.DELETE_MANY: Action.DELETE_MANY.value,
    # Ambiguous writes — default to insert; req.action overrides.
    Capability.WRITE_ONE: Action.INSERT_ONE.value,
    Capability.WRITE_MANY: Action.INSERT_MANY.value,
    # Ambiguous DDL — default to create/drop; req.action overrides.
    Capability.DDL_CREATE: Action.CREATE_INDEX.value,
    Capability.DDL_DESTROY: Action.DROP.value,
}


# #2 seam: operators the structured predicate AST may use, mapped to their
# Mongo-operator equivalent. Bare equality ({field: value}) is the default when
# op == "eq". This is the SAME bounded operator set CapabilityRequest.filter
# documents as the v1 portable contract.
_PREDICATE_OP_TO_MONGO: dict[str, str] = {
    "gt": "$gt",
    "gte": "$gte",
    "lt": "$lt",
    "lte": "$lte",
    "ne": "$ne",
    "in": "$in",
}


def compile_predicate_to_filter(predicate: dict[str, Any]) -> dict[str, Any]:
    """#2 seam: lower a simple predicate AST to the existing Mongo-operator
    `filter` dialect, so even today a predicate can be USED by lowering it to a
    filter (full native compilation is v2 work).

    Supported AST:
      leaf:  {"field": str, "op": one of eq/gt/gte/lt/lte/ne/in, "value": Any}
             op defaults to "eq" → bare equality {field: value}.
      and:   {"and": [<node>, ...]}  → {"$and": [<filter>, ...]}
      or:    {"or":  [<node>, ...]}  → {"$or":  [<filter>, ...]}

    Raises ValueError on an unrecognised op or malformed node.
    """
    if not isinstance(predicate, dict):
        raise ValueError("predicate must be a dict")

    if "and" in predicate:
        clauses = predicate["and"]
        if not isinstance(clauses, list):
            raise ValueError("'and' must be a list of predicate nodes")
        return {"$and": [compile_predicate_to_filter(c) for c in clauses]}
    if "or" in predicate:
        clauses = predicate["or"]
        if not isinstance(clauses, list):
            raise ValueError("'or' must be a list of predicate nodes")
        return {"$or": [compile_predicate_to_filter(c) for c in clauses]}

    # Leaf {field, op, value}.
    if "field" not in predicate:
        raise ValueError(f"predicate node missing 'field': {predicate!r}")
    field = predicate["field"]
    op = predicate.get("op", "eq")
    value = predicate.get("value")
    if op == "eq":
        return {field: value}
    mongo_op = _PREDICATE_OP_TO_MONGO.get(op)
    if mongo_op is None:
        raise ValueError(f"unsupported predicate op: {op!r}")
    return {field: {mongo_op: value}}
