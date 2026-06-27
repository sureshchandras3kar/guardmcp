from datetime import datetime
from typing import TYPE_CHECKING, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    field_validator,
    model_validator,
)

if TYPE_CHECKING:
    from ..masking.masker import FieldMasker, ResultTransformer


class CollectionPolicy(BaseModel):
    allow: list[str] = []
    deny: list[str] = []

    @model_validator(mode="after")
    def no_overlap(self) -> "CollectionPolicy":
        conflict = set(self.allow) & set(self.deny)
        if conflict:
            raise ValueError(f"collections appear in both allow and deny: {conflict}")
        return self


class ActionPolicy(BaseModel):
    allow: list[str] = []
    deny: list[str] = []


class ApprovalPolicy(BaseModel):
    high: bool = False
    critical: bool = False


class Policy(BaseModel):
    # Accept both snake_case and the camelCase YAML aliases (apiVersion).
    model_config = ConfigDict(populate_by_name=True)

    # apiVersion (forward-compat). Default keeps every existing flat file valid.
    # Accepts YAML key `apiVersion` (alias) or `api_version`. Validated at load.
    api_version: str = Field(default="guardmcp/v1", alias="apiVersion")
    agent: str
    # Role inheritance: names another policy in the same file to merge under.
    # A policy whose agent starts with "role:" is a base-only template — it is
    # resolvable via `extends` but never matched as a real agent by get().
    extends: str | None = None
    # Temporal validity window. If set, the policy is only active inside
    # [not_before, not_after]; outside it GuardPipeline.evaluate() denies.
    not_before: datetime | None = None
    not_after: datetime | None = None
    mode: str = "readonly"
    collections: CollectionPolicy = CollectionPolicy()
    actions: ActionPolicy = ActionPolicy()
    # mask_fields may be EITHER a flat list[str] (global — applies to every
    # collection, backward compatible) OR a dict[str, list[str]] mapping
    # collection name → fields, with "*" as the global bucket. Use
    # mask_fields_for(collection) to get the effective list.
    mask_fields: list[str] | dict[str, list[str]] = []
    # S-3: data-minimization allow-list. When non-empty, find/aggregate results
    # are projected to ONLY these top-level fields (plus _id), regardless of any
    # projection the agent requested. Empty = no field restriction (all
    # non-masked fields returned). This is enforced server-side on the RESULT,
    # so the agent cannot widen it.
    fields_allow: list[str] = []
    # S-6: which named connections this agent may switch to. Empty = all
    # allowed (backward compatible). Non-empty = an allow-list enforced by
    # GuardPipeline.switch_connection_audited before the switch happens.
    connections_allow: list[str] = []
    approval: ApprovalPolicy = ApprovalPolicy()

    # ── Cost-policy seam (Feature 1 — DOCUMENTED, NOT yet wired) ──────────────
    # A future "deny/escalate expensive operations" rule would add a `max_cost`
    # field here (e.g. max_cost: CostLevel = None) and have PolicyEngine.evaluate
    # consult it. It is intentionally NOT added as an accepted-but-unenforced
    # field: an unenforced security-looking knob misleads operators into thinking
    # expensive ops are blocked when they are not. The mechanics already exist —
    # RiskEngine.escalate_for_cost(base, cost) maps a HIGH/CRITICAL CostEstimate
    # to a higher RiskLevel, and guardmcp_plan surfaces both `cost` and
    # `cost_aware_risk`. Wiring this into live authorization requires moving the
    # estimation DB round-trip onto the authorize path (currently deliberately
    # avoided to keep evaluate() synchronous and cheap), so it is left as a seam.

    # M1: result transformer (field-allow + masking, fused) and audit masker are
    # built ONCE per policy and reused across requests, not rebuilt per call.
    # Masking is collection-dependent, so caches are keyed by collection name.
    _transformers: dict[str, Any] = PrivateAttr(default_factory=dict)
    _audit_maskers: dict[str, Any] = PrivateAttr(default_factory=dict)

    @field_validator("mode")
    @classmethod
    def mode_must_be_valid(cls, v: str) -> str:
        allowed = {"readonly", "readwrite"}
        if v not in allowed:
            raise ValueError(f"mode must be one of {sorted(allowed)}, got '{v}'")
        return v

    @field_validator("api_version")
    @classmethod
    def api_version_supported(cls, v: str) -> str:
        if not v.startswith("guardmcp/v"):
            raise ValueError(f"api_version must start with 'guardmcp/v', got '{v}'")
        # Only major v1 is understood by this build.
        major = v[len("guardmcp/v") :].split(".", 1)[0]
        if major != "1":
            raise ValueError(
                f"unsupported policy api_version '{v}': this build only "
                "understands major version 'guardmcp/v1'"
            )
        return v

    def is_role_template(self) -> bool:
        """True if this is a base-only role (agent starts with 'role:')."""
        return self.agent.startswith("role:")

    def mask_fields_for(self, collection: str) -> list[str]:
        """
        Effective mask fields for a collection. Flat list → global (same list
        for every collection). Dict → union of the "*" bucket and the
        per-collection bucket.
        """
        mf = self.mask_fields
        if isinstance(mf, dict):
            seen: dict[str, None] = {}
            for f in mf.get("*", []):
                seen[f] = None
            for f in mf.get(collection, []):
                seen[f] = None
            return list(seen)
        return mf

    def result_transformer(self, collection: str = "*") -> "ResultTransformer":
        """Cached single-pass field-allow + mask transformer (H3/M1)."""
        t = self._transformers.get(collection)
        if t is None:
            from ..masking.masker import ResultTransformer

            t = ResultTransformer(self.mask_fields_for(collection), self.fields_allow)
            self._transformers[collection] = t
        return t

    def audit_masker(self, collection: str = "*") -> "FieldMasker":
        """Cached mask-only masker for audit-param scrubbing + explain (M1)."""
        m = self._audit_maskers.get(collection)
        if m is None:
            from ..masking.masker import FieldMasker

            m = FieldMasker(self.mask_fields_for(collection))
            self._audit_maskers[collection] = m
        return m
