import pytest

from guardmcp.core.models.domain import Action
from guardmcp.core.pipeline import GuardPipeline
from guardmcp.core.policy.engine import PolicyEngine
from guardmcp.core.policy.models import CollectionPolicy, DatabaseScope, Policy
from guardmcp.core.risk.engine import RiskEngine


class _Loader:
    def __init__(self, p): self._p = p
    def get(self, agent): return self._p


class _Executor:
    def __init__(self): self.exec_calls = []
    async def execute(self, collection, action, params, database=None):
        self.exec_calls.append((collection, action, database))
        return {"documents": [{"_id": 1}], "count": 1}
    async def list_collections(self): return ["x"]


class _Audit:
    def build(self, **k): return k
    async def log(self, r): return None


def _pipeline(policy, executor):
    return GuardPipeline(policy_loader=_Loader(policy), policy_engine=PolicyEngine(),
                         risk_engine=RiskEngine(), audit_logger=_Audit(),
                         approval_store=None, executor=executor)


@pytest.mark.asyncio
async def test_run_denies_disallowed_database_on_execute_path():
    p = Policy(agent="claude", databases_allow=["db1"],
               databases={"db1": DatabaseScope(collections=CollectionPolicy(allow=["x"]))})
    ex = _Executor()
    res = await _pipeline(p, ex).run("claude", "x", Action.FIND, {"filter": {}}, database="db2")
    assert res["status"] == "denied"
    assert res["code"] == "DATABASE_NOT_ALLOWED"
    assert ex.exec_calls == []  # never executed


@pytest.mark.asyncio
async def test_run_threads_database_into_executor():
    p = Policy(agent="claude", databases_allow=["db1"],
               databases={"db1": DatabaseScope(collections=CollectionPolicy(allow=["x"]))})
    ex = _Executor()
    res = await _pipeline(p, ex).run("claude", "x", Action.FIND, {"filter": {}}, database="db1")
    assert res["status"] == "success"
    assert ("x", Action.FIND, "db1") in ex.exec_calls


@pytest.mark.asyncio
async def test_run_backcompat_no_database():
    p = Policy(agent="claude", collections=CollectionPolicy(allow=["x"]))
    ex = _Executor()
    res = await _pipeline(p, ex).run("claude", "x", Action.FIND, {"filter": {}})
    assert res["status"] == "success"
    assert ("x", Action.FIND, None) in ex.exec_calls


@pytest.mark.asyncio
async def test_execute_approved_threads_database():
    """Regression test: approval path must thread database into _execute_and_build."""
    p = Policy(agent="claude", databases_allow=["db1"],
               databases={"db1": DatabaseScope(collections=CollectionPolicy(allow=["x"]))})
    ex = _Executor()
    pipe = _pipeline(p, ex)
    # Use evaluate to build an EvalResult with database set on the request
    eval_result = pipe.evaluate("claude", "x", Action.FIND, {"filter": {}}, database="db1")
    # Call execute_approved with the EvalResult
    res = await pipe.execute_approved(eval_result)
    assert res["status"] == "success"
    # The executor must have been called with database="db1", not None
    assert ("x", Action.FIND, "db1") in ex.exec_calls
