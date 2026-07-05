from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

ROLE_PRIMARY = "primary_identifier"
ROLE_FOREIGN = "foreign_identifier"
ROLE_TENANT = "tenant_key"
ROLE_TIMESTAMP = "timestamp"
ROLE_ENUM = "enum_status"
ROLE_PII = "pii"
ROLE_NONE = "none"


class FieldStat(BaseModel):
    count: int
    null_count: int = 0
    distinct_count: int | None = None  # None = unknown/overflow
    sample_values: list[Any] | None = None


class FieldSemantics(BaseModel):
    role: str
    confidence: float = 0.0
    evidence: str = ""
    references: str | None = None  # target resource for foreign/tenant
    values: list[Any] | None = None  # enum value set (capped)
    pii: bool = False


class SemanticsInput(BaseModel):
    resource: str
    fields: dict[str, str] = Field(default_factory=dict)
    indexes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)  # outgoing FK edges
    fan_in: dict[str, int] = Field(default_factory=dict)  # field name -> #referencing collections
    field_stats: dict[str, FieldStat] = Field(default_factory=dict)
    masked_fields: list[str] = Field(default_factory=list)


class SemanticsResult(BaseModel):
    fields: dict[str, FieldSemantics] = Field(default_factory=dict)
