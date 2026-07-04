from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class Action(str, Enum):
    # Read ops
    FIND = "find"
    AGGREGATE = "aggregate"
    COUNT = "count"
    EXPLAIN = "explain"
    # Schema / introspection
    COLLECTION_SCHEMA = "collection_schema"
    COLLECTION_INDEXES = "collection_indexes"
    LIST_DATABASES = "list_databases"
    DB_STATS = "db_stats"
    # Write ops
    INSERT_ONE = "insert_one"
    INSERT_MANY = "insert_many"
    UPDATE_ONE = "update_one"
    UPDATE_MANY = "update_many"
    DELETE_ONE = "delete_one"
    DELETE_MANY = "delete_many"
    # DDL
    DROP = "drop"
    CREATE_INDEX = "create_index"
    DROP_INDEX = "drop_index"


# Action classifications — single source of truth, imported by all modules
WRITE_ACTIONS: frozenset["Action"] = frozenset(
    {
        Action.INSERT_ONE,
        Action.INSERT_MANY,
        Action.UPDATE_ONE,
        Action.UPDATE_MANY,
        Action.DELETE_ONE,
        Action.DELETE_MANY,
        Action.DROP,
        Action.CREATE_INDEX,
        Action.DROP_INDEX,
    }
)

# Actions that target the DB level — no collection required
DB_LEVEL_ACTIONS: frozenset["Action"] = frozenset(
    {
        Action.LIST_DATABASES,
        Action.DB_STATS,
    }
)

# Actions whose results are not document lists — skip field masking
NO_MASK_ACTIONS: frozenset["Action"] = frozenset(
    {
        Action.EXPLAIN,
        Action.COLLECTION_SCHEMA,
        Action.COLLECTION_INDEXES,
        Action.LIST_DATABASES,
        Action.DB_STATS,
        Action.INSERT_ONE,
        Action.INSERT_MANY,
        Action.UPDATE_ONE,
        Action.UPDATE_MANY,
        Action.DELETE_ONE,
        Action.DELETE_MANY,
        Action.CREATE_INDEX,
        Action.DROP_INDEX,
        Action.DROP,
    }
)


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class DecisionStatus(str, Enum):
    ALLOWED = "allowed"
    DENIED = "denied"
    APPROVAL_REQUIRED = "approval_required"


class Request(BaseModel):
    request_id: str = Field(default_factory=lambda: str(uuid4()))
    agent: str
    collection: str
    action: Action
    params: dict[str, Any] = Field(default_factory=dict)
    database: str | None = None


class Decision(BaseModel):
    status: DecisionStatus
    reason: str
    risk: RiskLevel | None = None
    # Machine-readable code stamped at the source for DENIED decisions, so the
    # server layer does not have to infer it from the reason string. Holds an
    # ErrorCode VALUE (e.g. "READONLY"). None for ALLOWED/APPROVAL_REQUIRED.
    code: str | None = None


class AuditRecord(BaseModel):
    timestamp: datetime
    agent: str
    collection: str
    action: str
    status: str
    reason: str | None = None
    risk: str | None = None
    request_id: str | None = None
    # Query content (filter/update/document/pipeline) for forensic reconstruction.
    # Sensitive values are scrubbed against policy mask_fields before logging.
    params: dict[str, Any] | None = None
    # Risk #5: identifies the writing process/replica. Default "" for single
    # process. In a multi-replica deployment set a unique GUARDMCP_NODE_ID per
    # replica so a centralized audit sink can attribute and aggregate by writer.
    node_id: str = ""
    # #8: correlation id shared between structured logs and this audit record,
    # so a single request can be traced across components at 3 AM. Stamped by
    # AuditLogger.build() from the current trace_id contextvar.
    trace_id: str = ""
    # Multi-database governance: which database this operation targeted.
    # Omitted from the serialised chain when None so single-DB HMAC chains
    # remain byte-identical to records written before this field existed.
    database: str | None = None
