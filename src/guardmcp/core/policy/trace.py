"""
Single-source-of-truth evaluation trace.

A `PolicyTrace` is an OPTIONAL recorder threaded through the EXISTING evaluation
path (GuardPipeline.evaluate -> PolicyEngine.evaluate). When supplied, each rule
check appends a `TraceStep` AT ITS EXISTING decision point, so the explanation
produced by `guardmcp_explain_policy` is generated FROM the same code that
authorizes a request — never a parallel evaluator.

When no trace is passed (the default / hot path), the engine guards every append
with `if trace is not None:`, so behavior and performance are IDENTICAL to a run
with no tracing at all.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TraceStep(BaseModel):
    """One recorded rule check.

    result is one of:
      - "matched"  : this rule produced the terminal decision
      - "passed"   : the rule was checked and the request satisfied it
      - "skipped"  : the rule did not apply to this request
    """

    model_config = ConfigDict(frozen=True)

    stage: str
    rule: str
    result: str
    detail: str | None = None


class PolicyTrace(BaseModel):
    """Mutable ordered recorder of evaluation steps.

    Not frozen — it accumulates steps as the engine runs. The public tool output
    model (PolicyExplanation) snapshots it into frozen models.
    """

    steps: list[TraceStep] = Field(default_factory=list)

    def add(self, stage: str, rule: str, result: str, detail: str | None = None) -> None:
        self.steps.append(TraceStep(stage=stage, rule=rule, result=result, detail=detail))
