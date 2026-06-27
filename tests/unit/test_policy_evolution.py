"""Tests for the evolved (non-flat) policy model: apiVersion, role inheritance
(extends), temporal validity, and per-collection masking. Everything here is
additive — flat policies are covered elsewhere and must still behave identically.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from guardmcp.core.approval.store import ApprovalStore
from guardmcp.core.audit.logger import AuditLogger
from guardmcp.core.models.domain import Action, DecisionStatus
from guardmcp.core.pipeline import GuardPipeline
from guardmcp.core.policy.engine import PolicyEngine
from guardmcp.core.policy.loader import PolicyLoader
from guardmcp.core.policy.models import Policy
from guardmcp.core.risk.engine import RiskEngine

# ── 1. apiVersion ─────────────────────────────────────────────────────────────


class TestApiVersion:
    def test_default(self):
        assert Policy(agent="a").api_version == "guardmcp/v1"

    def test_alias_accepted(self):
        p = Policy.model_validate({"agent": "a", "apiVersion": "guardmcp/v1"})
        assert p.api_version == "guardmcp/v1"

    def test_bad_prefix_raises(self):
        with pytest.raises(ValueError):
            Policy(agent="a", api_version="v2")

    def test_unknown_major_raises(self):
        with pytest.raises(ValueError):
            Policy.model_validate({"agent": "a", "apiVersion": "guardmcp/v2"})


# ── 2. Role inheritance (extends) ─────────────────────────────────────────────


def _write(tmp_path: Path, docs) -> PolicyLoader:
    f = tmp_path / "policy.yaml"
    f.write_text(yaml.safe_dump(docs))
    loader = PolicyLoader(f)
    loader.load()
    return loader


class TestExtends:
    def test_union_of_collections(self, tmp_path):
        loader = _write(
            tmp_path,
            {
                "agents": [
                    {"agent": "role:reader", "collections": {"allow": ["a", "b"]}},
                    {"agent": "child", "extends": "role:reader", "collections": {"allow": ["c"]}},
                ]
            },
        )
        child = loader.get("child")
        assert set(child.collections.allow) == {"a", "b", "c"}
        # The role template itself is not a matchable agent.
        assert loader.get("role:reader") is None

    def test_child_mode_overrides_base(self, tmp_path):
        loader = _write(
            tmp_path,
            {
                "agents": [
                    {"agent": "role:rw", "mode": "readwrite", "actions": {"allow": ["find"]}},
                    {"agent": "child", "extends": "role:rw", "actions": {"allow": ["insert_one"]}},
                ]
            },
        )
        child = loader.get("child")
        assert child.mode == "readwrite"
        assert set(child.actions.allow) == {"find", "insert_one"}

    def test_approval_merge(self, tmp_path):
        loader = _write(
            tmp_path,
            {
                "agents": [
                    {"agent": "role:base", "approval": {"high": True}},
                    {"agent": "child", "extends": "role:base", "approval": {"critical": True}},
                ]
            },
        )
        child = loader.get("child")
        assert child.approval.high is True
        assert child.approval.critical is True

    def test_cycle_raises(self, tmp_path):
        f = tmp_path / "policy.yaml"
        f.write_text(
            yaml.safe_dump(
                {
                    "agents": [
                        {"agent": "a", "extends": "b"},
                        {"agent": "b", "extends": "a"},
                    ]
                }
            )
        )
        loader = PolicyLoader(f)
        with pytest.raises(ValueError, match="cyclic"):
            loader.load()

    def test_missing_base_raises(self, tmp_path):
        f = tmp_path / "policy.yaml"
        f.write_text(
            yaml.safe_dump(
                {
                    "agents": [
                        {"agent": "a", "extends": "ghost"},
                    ]
                }
            )
        )
        loader = PolicyLoader(f)
        with pytest.raises(ValueError, match="unknown base"):
            loader.load()


# ── 3. Temporal validity ──────────────────────────────────────────────────────


def _pipeline_with(policy: Policy) -> GuardPipeline:
    class _Loader:
        def get(self, agent):
            return policy if agent == policy.agent else None

    class _Executor:
        async def execute(self, *a, **k):
            return {"documents": []}

    import tempfile

    audit = AuditLogger(Path(tempfile.mkdtemp()) / "audit.jsonl")
    return GuardPipeline(
        policy_loader=_Loader(),
        policy_engine=PolicyEngine(),
        risk_engine=RiskEngine(),
        audit_logger=audit,
        approval_store=ApprovalStore(timeout_seconds=0.001),
        executor=_Executor(),
    )


class TestTemporal:
    def test_expired_denies(self):
        past = datetime.now(UTC) - timedelta(days=1)
        policy = Policy(
            agent="t",
            actions={"allow": ["find"]},
            collections={"allow": ["c"]},
            not_after=past,
        )
        pipe = _pipeline_with(policy)
        res = pipe.evaluate("t", "c", Action.FIND, {"filter": {}})
        assert res.decision.status == DecisionStatus.DENIED
        assert "not active at this time" in res.decision.reason

    def test_future_window_denies(self):
        future = datetime.now(UTC) + timedelta(days=1)
        policy = Policy(
            agent="t",
            actions={"allow": ["find"]},
            collections={"allow": ["c"]},
            not_before=future,
        )
        pipe = _pipeline_with(policy)
        res = pipe.evaluate("t", "c", Action.FIND, {"filter": {}})
        assert res.decision.status == DecisionStatus.DENIED

    def test_within_window_allows(self):
        nb = datetime.now(UTC) - timedelta(days=1)
        na = datetime.now(UTC) + timedelta(days=1)
        policy = Policy(
            agent="t",
            actions={"allow": ["find"]},
            collections={"allow": ["c"]},
            not_before=nb,
            not_after=na,
        )
        pipe = _pipeline_with(policy)
        res = pipe.evaluate("t", "c", Action.FIND, {"filter": {}})
        assert res.decision.status == DecisionStatus.ALLOWED

    def test_no_window_unaffected(self):
        policy = Policy(
            agent="t",
            actions={"allow": ["find"]},
            collections={"allow": ["c"]},
        )
        pipe = _pipeline_with(policy)
        res = pipe.evaluate("t", "c", Action.FIND, {"filter": {}})
        assert res.decision.status == DecisionStatus.ALLOWED


# ── 4. Per-collection masking ─────────────────────────────────────────────────


class TestPerCollectionMask:
    def test_dict_form(self):
        p = Policy(agent="a", mask_fields={"users": ["ssn"], "*": ["password"]})
        assert sorted(p.mask_fields_for("users")) == ["password", "ssn"]
        assert p.mask_fields_for("other") == ["password"]

    def test_flat_list_stays_global(self):
        p = Policy(agent="a", mask_fields=["password", "token"])
        assert p.mask_fields_for("users") == ["password", "token"]
        assert p.mask_fields_for("anything") == ["password", "token"]

    def test_empty_default(self):
        p = Policy(agent="a")
        assert p.mask_fields_for("users") == []

    def test_transformers_cached_per_collection(self):
        p = Policy(agent="a", mask_fields={"users": ["ssn"], "*": ["password"]})
        t_users = p.result_transformer("users")
        t_other = p.result_transformer("other")
        assert t_users is not t_other
        # cached: same object on repeat
        assert p.result_transformer("users") is t_users

    def test_per_collection_masking_applied(self):
        p = Policy(agent="a", mask_fields={"users": ["ssn"], "*": ["password"]})
        out_users = p.result_transformer("users").transform_result(
            [{"ssn": "x", "password": "y", "name": "n"}]
        )
        assert out_users[0]["ssn"] == "***masked***"
        assert out_users[0]["password"] == "***masked***"
        assert out_users[0]["name"] == "n"
        out_other = p.result_transformer("other").transform_result([{"ssn": "x", "password": "y"}])
        assert out_other[0]["ssn"] == "x"  # not masked outside users
        assert out_other[0]["password"] == "***masked***"


# ── Backward compatibility: existing flat policy files still load ─────────────


class TestBackwardCompat:
    def test_example_policy_loads(self):
        loader = PolicyLoader(Path("policies/example.yaml"))
        loader.load()
        p = loader.get("support-bot")
        assert p is not None
        assert p.api_version == "guardmcp/v1"
        assert isinstance(p.mask_fields, list)
