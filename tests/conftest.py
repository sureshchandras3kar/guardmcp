import pytest
import pytest_asyncio
from mongomock_motor import AsyncMongoMockClient

from guardmcp.core.approval.store import ApprovalStore
from guardmcp.core.audit.logger import AuditLogger
from guardmcp.core.pipeline import GuardPipeline
from guardmcp.core.policy.engine import PolicyEngine
from guardmcp.core.policy.loader import PolicyLoader
from guardmcp.core.risk.engine import RiskEngine
from guardmcp.plugins.mongodb.executor import MongoExecutor


@pytest.fixture
def policy_file(tmp_path):
    p = tmp_path / "policy.yaml"
    p.write_text("""
agent: test-agent
mode: readonly
collections:
  allow:
    - customers
    - orders
  deny:
    - payroll
actions:
  allow:
    - find
    - aggregate
    - count
    - explain
    - collection_schema
    - collection_indexes
    - list_databases
    - db_stats
mask_fields:
  - email
  - password
approval:
  high: true
  critical: true
""")
    return p


@pytest.fixture
def policy_loader(policy_file):
    loader = PolicyLoader(policy_file)
    loader.load()
    return loader


@pytest.fixture
def mock_mongo_client(monkeypatch):
    """Mongomock-based client — no real MongoDB needed."""
    real_client = AsyncMongoMockClient()

    class _Client:
        def get_collection(self, name, database=None):
            return real_client["testdb"][name]

        def get_db(self, database=None):
            return real_client["testdb"]

        async def list_collection_names(self, database=None):
            return await real_client["testdb"].list_collection_names()

        async def list_databases(self):  # noqa: RUF029 – async for consistent interface
            return [{"name": "testdb", "sizeOnDisk": 0}]

        def close(self):
            pass

    return _Client()


@pytest.fixture
def executor(mock_mongo_client):
    return MongoExecutor(mock_mongo_client)


@pytest.fixture
def approval_store():
    return ApprovalStore(timeout_seconds=1.0)


@pytest.fixture
def audit_logger(tmp_path):
    return AuditLogger(tmp_path / "audit.jsonl")


@pytest_asyncio.fixture
async def pipeline(policy_loader, executor, approval_store, audit_logger):
    return GuardPipeline(
        policy_loader=policy_loader,
        policy_engine=PolicyEngine(),
        risk_engine=RiskEngine(),
        audit_logger=audit_logger,
        approval_store=approval_store,
        executor=executor,
    )
