"""S-3: field allow-list enforced end-to-end through GuardPipeline.run (FIND)."""

import pytest_asyncio

from guardmcp.core.masking.masker import MASK_VALUE
from guardmcp.core.models.domain import Action
from guardmcp.core.pipeline import GuardPipeline
from guardmcp.core.policy.engine import PolicyEngine
from guardmcp.core.risk.engine import RiskEngine


class _StubLoader:
    """Minimal policy loader exposing the single .get(agent) used by pipeline."""

    def __init__(self, policy):
        self._policy = policy

    def get(self, agent):
        return self._policy


def _make_policy(**overrides):
    from guardmcp.core.policy.models import ActionPolicy, CollectionPolicy, Policy

    base = dict(
        agent="test-agent",
        mode="readonly",
        collections=CollectionPolicy(allow=["customers"]),
        actions=ActionPolicy(allow=["find"]),
    )
    base.update(overrides)
    return Policy(**base)


@pytest_asyncio.fixture
async def pipeline_with(executor, approval_store, audit_logger):
    def _factory(policy):
        return GuardPipeline(
            policy_loader=_StubLoader(policy),
            policy_engine=PolicyEngine(),
            risk_engine=RiskEngine(),
            audit_logger=audit_logger,
            approval_store=approval_store,
            executor=executor,
        )

    return _factory


async def test_field_allow_drops_disallowed_fields(pipeline_with, mock_mongo_client):
    col = mock_mongo_client.get_collection("customers")
    await col.insert_one({"name": "Alice", "email": "a@b.com", "ssn": "123", "role": "admin"})
    policy = _make_policy(fields_allow=["name", "role"])
    pipeline = pipeline_with(policy)

    result = await pipeline.run("test-agent", "customers", Action.FIND, {"filter": {}, "limit": 10})
    assert result["status"] == "success"
    docs = result["data"]["documents"]
    assert len(docs) == 1
    doc = docs[0]
    assert set(doc.keys()) == {"_id", "name", "role"}
    assert "email" not in doc
    assert "ssn" not in doc


async def test_field_allow_with_masking(pipeline_with, mock_mongo_client):
    col = mock_mongo_client.get_collection("customers")
    await col.insert_one({"name": "Alice", "email": "a@b.com", "ssn": "123", "role": "admin"})
    policy = _make_policy(fields_allow=["name", "role"], mask_fields=["name"])
    pipeline = pipeline_with(policy)

    result = await pipeline.run("test-agent", "customers", Action.FIND, {"filter": {}, "limit": 10})
    assert result["status"] == "success"
    doc = result["data"]["documents"][0]
    assert doc["name"] == MASK_VALUE
    assert doc["role"] == "admin"
    assert "email" not in doc
