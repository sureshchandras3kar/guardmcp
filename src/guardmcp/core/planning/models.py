from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from ..interfaces.capability import CapabilityRequest
from ..interfaces.cost import CostEstimate

RelationshipKind = Literal["fk", "index", "naming", "sampled"]


class Relationship(BaseModel):
    from_resource: str
    from_field: str
    to_resource: str
    to_field: str
    kind: RelationshipKind
    confidence: float
    evidence: str


class RelationshipGraph(BaseModel):
    nodes: list[str] = Field(default_factory=list)
    edges: list[Relationship] = Field(default_factory=list)
    generated_at: str
    cached: bool = False


class Interpretation(BaseModel):
    field: str
    operator: str
    value: Any = None
    confidence: float
    evidence: str


class AmbiguityReport(BaseModel):
    ambiguous: bool
    confidence: float
    interpretations: list[Interpretation] = Field(default_factory=list)
    recommendation: str = ""


class ExecutionPlan(BaseModel):
    strategy: str
    request: CapabilityRequest
    relationships_used: list[Relationship] = Field(default_factory=list)
    est_cost: CostEstimate | None = None
    complexity: str = "unknown"
    index_used: bool | None = None
    risk_level: str | None = None
    governance: dict[str, Any] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)


class AlternativePlan(ExecutionPlan):
    rank: int = 0
    tradeoff: str = ""


class PlanningContext(BaseModel):
    agent: str
    intent: str
    resource: str | None = None
    allowed_resources: list[str] = Field(default_factory=list)
    resource_schema: dict[str, Any] = Field(default_factory=dict)
    indexes: list[dict[str, Any]] = Field(default_factory=list)
    relationships: RelationshipGraph


class PlannerResult(BaseModel):
    ambiguity: AmbiguityReport
    relationships: RelationshipGraph
    plans: list[AlternativePlan] = Field(default_factory=list)
    recommended_plan: AlternativePlan | None = None
    notes: list[str] = Field(default_factory=list)


class CrossDbEndpoint(BaseModel):
    database: str
    collection: str
    field: str


class CrossDbEdge(BaseModel):
    model_config = {"populate_by_name": True}
    from_: CrossDbEndpoint = Field(alias="from")
    to: CrossDbEndpoint
    kind: str  # "shared_name" | "value_overlap"
    confidence: float
    overlap_ratio: float | None = None
    evidence: str = ""
