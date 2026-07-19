"""db_export — writes an ALREADY-MASKED find/aggregate result to a local file.
Real MongoExecutor + mongomock-motor (find/aggregate work natively there,
unlike collStats/getLog/db-level-aggregate). Masking-safety is the critical
property under test: an exported file must never contain a masked field's
real value.
"""

import json

import pytest
from mcp.server.fastmcp import FastMCP
from mongomock_motor import AsyncMongoMockClient

from guardmcp.core.approval.store import ApprovalStore
from guardmcp.core.audit.logger import AuditLogger
from guardmcp.core.export import sweep_expired, write_export
from guardmcp.core.pipeline import GuardPipeline
from guardmcp.core.policy.engine import PolicyEngine
from guardmcp.core.policy.loader import PolicyLoader
from guardmcp.core.risk.engine import RiskEngine
from guardmcp.plugins.mongodb.executor import MongoExecutor
from guardmcp.server import tools as tools_mod
from guardmcp.server.tools._common import ToolContext


class _Settings:
    def __init__(self, export_dir, ttl=300.0):
        self.export_dir = export_dir
        self.export_ttl_seconds = ttl


def _make_client():
    real = AsyncMongoMockClient()

    class _Client:
        def get_collection(self, name, database=None):
            return real["testdb"][name]

        def get_db(self, database=None):
            return real["testdb"]

        async def list_collection_names(self, database=None):
            return await real["testdb"].list_collection_names()

        async def list_databases(self):  # noqa: RUF029
            return [{"name": "testdb", "sizeOnDisk": 0}]

        def close(self):
            pass

    return _Client(), real


async def _pipeline(tmp_path, policy_yaml: str):
    pol = tmp_path / "policy.yaml"
    pol.write_text(policy_yaml)
    loader = PolicyLoader(pol)
    loader.load()
    client, real = _make_client()
    pipeline = GuardPipeline(
        policy_loader=loader,
        policy_engine=PolicyEngine(),
        risk_engine=RiskEngine(),
        audit_logger=AuditLogger(tmp_path / "audit.jsonl"),
        approval_store=ApprovalStore(timeout_seconds=1.0),
        executor=MongoExecutor(client),
    )
    return pipeline, real


def _get_tool(pipeline, settings, name):
    mcp = FastMCP("test")
    ctx = ToolContext(
        get_pipeline=lambda: pipeline, get_agent=lambda: "test-agent",
        get_settings=lambda: settings,
    )
    tools_mod.export.register(mcp, ctx)
    return mcp._tool_manager.get_tool(name)


async def _call(tool, **kwargs):
    return json.loads(await tool.fn(**kwargs))


_ALLOW_POLICY = """
agent: test-agent
mode: readonly
collections:
  allow: [users]
mask_fields:
  - ssn
"""


@pytest.mark.asyncio
async def test_export_find_writes_masked_data_and_returns_manifest(tmp_path):
    pipeline, real = await _pipeline(tmp_path, _ALLOW_POLICY)
    await real["testdb"]["users"].insert_many(
        [{"name": "a", "ssn": "111-22-3333"}, {"name": "b", "ssn": "444-55-6666"}]
    )
    export_dir = tmp_path / "exports"
    settings = _Settings(export_dir)
    tool = _get_tool(pipeline, settings, "db_export")

    out = await _call(tool, collection="users", mode="find")

    assert out["ok"] is True
    manifest = out["data"]
    assert manifest["document_count"] == 2
    assert manifest["size_bytes"] > 0

    written = json.loads((export_dir / f"{manifest['export_id']}.json").read_text())
    assert len(written) == 2
    # CRITICAL: masked field's real value must never appear in the export file.
    assert all(doc["ssn"] != "111-22-3333" and doc["ssn"] != "444-55-6666" for doc in written)
    assert "***" in written[0]["ssn"] or written[0]["ssn"] != "111-22-3333"


@pytest.mark.asyncio
async def test_export_aggregate_mode(tmp_path):
    pipeline, real = await _pipeline(tmp_path, _ALLOW_POLICY)
    await real["testdb"]["users"].insert_many([{"name": "a"}, {"name": "b"}])
    settings = _Settings(tmp_path / "exports")
    tool = _get_tool(pipeline, settings, "db_export")

    out = await _call(
        tool, collection="users", mode="aggregate",
        pipeline_stages=[{"$match": {}}, {"$project": {"name": 1}}],
    )

    assert out["ok"] is True
    assert out["data"]["document_count"] == 2


@pytest.mark.asyncio
async def test_export_denied_no_file_written(tmp_path):
    pipeline, real = await _pipeline(
        tmp_path,
        """
agent: test-agent
mode: readonly
collections:
  allow: [users]
""",
    )
    export_dir = tmp_path / "exports"
    settings = _Settings(export_dir)
    tool = _get_tool(pipeline, settings, "db_export")

    out = await _call(tool, collection="not_allowed", mode="find")

    assert out["ok"] is False
    assert not export_dir.exists() or list(export_dir.glob("*.json")) == []


# ── core/export.py: pure functions ──────────────────────────────────────────


def test_write_export_manifest_shape(tmp_path):
    manifest = write_export(tmp_path, [{"a": 1}, {"a": 2}])
    assert manifest["document_count"] == 2
    assert manifest["size_bytes"] > 0
    assert (tmp_path / f"{manifest['export_id']}.json").exists()
    # Filename is a UUID, never derived from the data.
    import uuid

    uuid.UUID(manifest["export_id"])  # raises if not a valid UUID


def test_sweep_expired_removes_old_keeps_fresh(tmp_path):
    old = tmp_path / "old.json"
    old.write_text("[]")
    fresh = tmp_path / "fresh.json"
    fresh.write_text("[]")
    import os
    import time

    old_time = time.time() - 1000
    os.utime(old, (old_time, old_time))

    removed = sweep_expired(tmp_path, ttl_seconds=300.0)
    assert removed == 1
    assert not old.exists()
    assert fresh.exists()


def test_sweep_expired_nonexistent_dir_is_noop(tmp_path):
    assert sweep_expired(tmp_path / "does_not_exist", ttl_seconds=300.0) == 0
