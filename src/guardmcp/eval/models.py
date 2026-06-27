"""Domain models for the GuardMCP eval framework."""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ExpectedDecision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    APPROVAL_REQUIRED = "approval_required"


class EvalRequest(BaseModel):
    agent: str = "test-agent"
    collection: str = ""
    action: str
    params: dict[str, Any] = Field(default_factory=dict)


class FixtureDoc(BaseModel):
    collection: str
    documents: list[dict[str, Any]] = Field(default_factory=list)


class InlinePolicy(BaseModel):
    agent: str = "test-agent"
    mode: str = "readonly"
    collections: dict[str, Any] = Field(default_factory=dict)
    actions: dict[str, Any] = Field(default_factory=dict)
    # mask_fields may be a flat list[str] (global) OR a dict[str, list[str]]
    # mapping collection -> fields (with "*" as the global bucket), mirroring
    # core Policy.mask_fields. Both shapes pass through to Policy unchanged.
    mask_fields: list[str] | dict[str, list[str]] = Field(default_factory=list)
    # S-3: data-minimization allow-list — when non-empty, find/aggregate results
    # are projected to ONLY these top-level fields (+ _id) server-side.
    fields_allow: list[str] = Field(default_factory=list)
    # S-6: named connections this agent may switch to (eval-expressible).
    connections_allow: list[str] = Field(default_factory=list)
    approval: dict[str, Any] = Field(default_factory=dict)


class ExpectedResult(BaseModel):
    # Decision-level (uses pipeline.evaluate — no side effects)
    decision: ExpectedDecision | None = None

    # Execution-level (uses pipeline.run)
    status: str | None = None  # success | denied | error

    # Approval
    approval_required: bool | None = None
    simulate_approval: str = "deny"  # approve | deny

    # Reason text
    reason_contains: str | None = None
    reason_matches: str | None = None  # regex

    # Masking (dot-notation supported: "contact.email")
    masked_fields: list[str] = Field(default_factory=list)
    unmasked_fields: list[str] = Field(default_factory=list)

    # Data
    data_count: int | None = None
    data_contains: list[dict[str, Any]] = Field(default_factory=list)

    # Error
    error_contains: str | None = None


class EvalCase(BaseModel):
    name: str
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    skip: bool = False
    skip_reason: str | None = None
    policy: InlinePolicy
    fixtures: list[FixtureDoc] = Field(default_factory=list)
    request: EvalRequest
    expected: ExpectedResult


class EvalCaseResult(BaseModel):
    case_name: str
    passed: bool
    skipped: bool = False
    skip_reason: str | None = None
    failures: list[str] = Field(default_factory=list)
    actual: dict[str, Any] | None = None
    decision_status: str | None = None
    duration_ms: float = 0.0
    tags: list[str] = Field(default_factory=list)


class EvalReport(BaseModel):
    total: int
    passed: int
    failed: int
    skipped: int
    duration_ms: float
    results: list[EvalCaseResult]
