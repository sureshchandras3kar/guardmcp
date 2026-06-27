"""
Public, frozen output models + helpers for the policy Explain and Simulate
MCP tools (Features 2 and 3).

SINGLE SOURCE OF TRUTH: neither feature contains policy-decision logic. Explain
reads a PolicyTrace produced by the real engine; Simulate diffs two Policy models
and reports decisions produced by running the SAME GuardPipeline.evaluate against
each policy (via the additive `policy_override` parameter). No second evaluator.
"""

from __future__ import annotations

from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from .loader import _resolve_inheritance
from .models import Policy
from .trace import PolicyTrace

# ── Frozen public output models ──────────────────────────────────────────────


class MatchedRule(BaseModel):
    model_config = ConfigDict(frozen=True)

    rule: str
    result: str


class PolicyExplanation(BaseModel):
    """Public contract for guardmcp_explain_policy."""

    model_config = ConfigDict(frozen=True)

    decision: str  # ALLOWED | DENIED | APPROVAL_REQUIRED
    risk: str | None = None
    approval_required: bool = False
    matched_rules: list[MatchedRule] = Field(default_factory=list)
    evaluation_trace: list[str] = Field(default_factory=list)
    reason: str
    code: str | None = None


class SimulationImpact(BaseModel):
    model_config = ConfigDict(frozen=True)

    security: str  # LOW | MEDIUM | HIGH
    behavior_change: bool


class PolicySimulation(BaseModel):
    """Public contract for guardmcp_simulate_policy."""

    model_config = ConfigDict(frozen=True)

    current_decision: str
    proposed_decision: str
    decision_changed: bool
    risk: str | None = None
    approval_required: bool = False
    changed_rules: list[str] = Field(default_factory=list)
    impact: SimulationImpact


# ── Explain: snapshot a finished trace into the public model ─────────────────


def build_explanation(decision, trace: PolicyTrace) -> PolicyExplanation:
    """Build a PolicyExplanation from a Decision + the trace the engine filled.

    Pure projection of the engine's own output — no decision logic here. Only
    rule labels + results are exposed (no raw policy dump, no stack).
    """
    from ..models.domain import DecisionStatus

    matched = [
        MatchedRule(rule=s.rule, result=s.result) for s in trace.steps if s.result == "matched"
    ]
    return PolicyExplanation(
        decision=decision.status.name,
        risk=decision.risk.value if decision.risk else None,
        approval_required=decision.status == DecisionStatus.APPROVAL_REQUIRED,
        matched_rules=matched,
        evaluation_trace=[s.stage for s in trace.steps],
        reason=decision.reason,
        code=decision.code,
    )


# ── Simulate: parse policy input via the SAME loader path ────────────────────


def build_policy_from_input(spec: dict[str, Any] | str, *, agent: str | None = None) -> Policy:
    """Build a fully-resolved Policy from a dict or YAML string.

    Reuses the loader's Policy model + `_resolve_inheritance` so `extends` chains
    resolve EXACTLY as on-disk policies do. A YAML string may carry a single
    policy, a list, or an {agents: [...]} doc; when multiple are present the one
    named by `agent` (else the first non-role) is returned, fully merged.
    """
    data = yaml.safe_load(spec) if isinstance(spec, str) else spec

    if data is None:
        raise ValueError("policy spec is empty")

    if isinstance(data, list):
        items = data
    elif isinstance(data, dict) and "agents" in data:
        items = data["agents"]
    else:
        items = [data]

    parsed: dict[str, Policy] = {}
    for item in items:
        p = Policy.model_validate(item)
        parsed[p.agent] = p

    resolved = _resolve_inheritance(parsed)

    if agent is not None and agent in resolved:
        return resolved[agent]
    # Prefer the first real (non-role) policy.
    for p in resolved.values():
        if not p.is_role_template():
            return p
    # Only role templates present — return the first.
    return next(iter(resolved.values()))


# ── Simulate: field-by-field diff of two Policy models ───────────────────────


def _sorted(seq) -> list[str]:
    return sorted(str(x) for x in seq)


def diff_policies(current: Policy, proposed: Policy) -> list[str]:
    """Human-readable diffs between two Policy objects (no decision logic)."""
    out: list[str] = []

    # Mode
    if current.mode != proposed.mode:
        if current.mode == "readonly" and proposed.mode == "readwrite":
            out.append("Removed readonly mode (now readwrite)")
        elif current.mode == "readwrite" and proposed.mode == "readonly":
            out.append("Added readonly mode (now readonly)")
        else:
            out.append(f"Changed mode {current.mode} -> {proposed.mode}")

    # Collections allow / deny
    for label, cur_l, prop_l in (
        ("collections.allow", current.collections.allow, proposed.collections.allow),
        ("collections.deny", current.collections.deny, proposed.collections.deny),
        ("actions.allow", current.actions.allow, proposed.actions.allow),
        ("actions.deny", current.actions.deny, proposed.actions.deny),
        ("connections_allow", current.connections_allow, proposed.connections_allow),
        ("fields_allow", current.fields_allow, proposed.fields_allow),
    ):
        cur_s, prop_s = set(cur_l), set(prop_l)
        added = _sorted(prop_s - cur_s)
        removed = _sorted(cur_s - prop_s)
        for item in added:
            out.append(f"Added {item} to {label}")
        for item in removed:
            out.append(f"Removed {item} from {label}")

    # Masks (collection-aware — compare effective union via mask_fields_for("*")
    # plus any per-collection buckets present in either policy)
    cur_mask = _effective_mask_map(current)
    prop_mask = _effective_mask_map(proposed)
    for col in sorted(set(cur_mask) | set(prop_mask)):
        cur_f = set(cur_mask.get(col, []))
        prop_f = set(prop_mask.get(col, []))
        suffix = "" if col == "*" else f" (collection '{col}')"
        for f in _sorted(prop_f - cur_f):
            out.append(f"Now masks: {f}{suffix}")
        for f in _sorted(cur_f - prop_f):
            out.append(f"No longer masks: {f}{suffix}")

    # Approval toggles
    if current.approval.high != proposed.approval.high:
        out.append(
            "Enabled approval for HIGH risk"
            if proposed.approval.high
            else "Disabled approval for HIGH risk"
        )
    if current.approval.critical != proposed.approval.critical:
        out.append(
            "Enabled approval for CRITICAL risk"
            if proposed.approval.critical
            else "Disabled approval for CRITICAL risk"
        )

    # Temporal
    if current.not_before != proposed.not_before:
        out.append(f"Changed not_before -> {proposed.not_before}")
    if current.not_after != proposed.not_after:
        out.append(f"Changed not_after -> {proposed.not_after}")

    # Extends (post-resolution this is normally None, but surface if differs)
    if current.extends != proposed.extends:
        out.append(f"Changed extends -> {proposed.extends}")

    return out


def _effective_mask_map(policy: Policy) -> dict[str, list[str]]:
    """Normalize mask_fields to a {collection: [fields]} map. Flat list -> {"*": ...}."""
    mf = policy.mask_fields
    if isinstance(mf, dict):
        return {k: list(v) for k, v in mf.items()}
    return {"*": list(mf)} if mf else {}


# ── Simulate: security-impact heuristic ──────────────────────────────────────

_WIDENING_PREFIXES = (
    "Removed readonly mode",
    "Added ",  # added collection/action/connection/field to an allow list widens
    "No longer masks",
    "Disabled approval",
)
_NARROWING_PREFIXES = (
    "Added readonly mode",
    "Removed ",  # removed from an allow list narrows
    "Now masks",
    "Enabled approval",
)


def classify_impact(changed_rules: list[str], *, behavior_change: bool) -> SimulationImpact:
    """Heuristic security rating from the human-readable diffs.

    HIGH if any change widens access; MEDIUM if changes are mixed (both widen
    and narrow); LOW if it only narrows or is a no-op.
    """
    widens = False
    narrows = False
    for line in changed_rules:
        # "Added X to actions.deny" / "...collections.deny" NARROWS, not widens.
        if line.startswith("Added ") and (
            " to actions.deny" in line or " to collections.deny" in line
        ):
            narrows = True
            continue
        if line.startswith("Removed ") and (
            " from actions.deny" in line or " from collections.deny" in line
        ):
            widens = True
            continue
        if any(line.startswith(p) for p in _WIDENING_PREFIXES):
            widens = True
        elif any(line.startswith(p) for p in _NARROWING_PREFIXES):
            narrows = True

    if widens and narrows:
        security: Literal["LOW", "MEDIUM", "HIGH"] = "MEDIUM"
    elif widens:
        security = "HIGH"
    else:
        security = "LOW"

    return SimulationImpact(security=security, behavior_change=behavior_change)
