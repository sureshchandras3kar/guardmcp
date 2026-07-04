import pytest

from guardmcp.core.pipeline import GuardPipeline
from guardmcp.core.policy.engine import PolicyEngine
from guardmcp.core.policy.models import CollectionPolicy, DatabaseScope, Policy
from guardmcp.core.risk.engine import RiskEngine


class _Loader:
    def __init__(self, p): self._p = p
    def get(self, agent): return self._p


class _Executor:
    def __init__(self): self.calls = []
    async def list_collections(self, database=None):
        self.calls.append(("list", database))
        return ["user"]

    async def collection_schema(self, collection, mask_fields, sample_size=None, database=None):
        self.calls.append(("schema", collection, database))
        return {"_id": "objectId"}


class _Audit:
    def build(self, **k): return k
    async def log(self, r): return None


def _pipeline(p, ex):
    return GuardPipeline(policy_loader=_Loader(p), policy_engine=PolicyEngine(),
                         risk_engine=RiskEngine(), audit_logger=_Audit(),
                         approval_store=None, executor=ex)


@pytest.mark.asyncio
async def test_discover_collections_threads_database():
    p = Policy(agent="claude", databases_allow=["db1"],
               databases={"db1": DatabaseScope(collections=CollectionPolicy(allow=["user"]))})
    ex = _Executor()
    cols = await _pipeline(p, ex).discover_collections("claude", database="db1")
    assert cols == ["user"] and ("list", "db1") in ex.calls


@pytest.mark.asyncio
async def test_describe_collection_threads_database():
    p = Policy(agent="claude", databases_allow=["db1"],
               databases={"db1": DatabaseScope(collections=CollectionPolicy(allow=["user"]))})
    ex = _Executor()
    out = await _pipeline(p, ex).describe_collection("claude", "user", database="db1")
    assert out is not None and any(c == ("schema", "user", "db1") for c in ex.calls)


@pytest.mark.asyncio
async def test_discovery_backcompat_no_database():
    p = Policy(agent="claude", collections=CollectionPolicy(allow=["user"]))
    ex = _Executor()
    await _pipeline(p, ex).discover_collections("claude")
    assert ("list", None) in ex.calls


@pytest.mark.asyncio
async def test_describe_collection_backcompat_no_database():
    """Regression: describe_collection with no database still works for flat policies."""
    p = Policy(agent="claude", collections=CollectionPolicy(allow=["user"]))
    ex = _Executor()
    out = await _pipeline(p, ex).describe_collection("claude", "user")
    assert out is not None  # flat policy still permits and describes
    assert any(
        c == ("schema", "user", None) for c in ex.calls
    )  # executor called with database=None
