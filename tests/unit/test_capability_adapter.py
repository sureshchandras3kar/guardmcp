import pytest

from guardmcp.core.interfaces.capability import (
    Capability,
    CapabilityRequest,
    CapabilityResult,
)
from guardmcp.core.interfaces.errors import GuardValidationError
from guardmcp.core.interfaces.plugin import DatabasePlugin
from guardmcp.core.models.domain import Action
from guardmcp.core.registry.adapter import CapabilityExecutorAdapter


class FakePlugin(DatabasePlugin):
    """A DatabasePlugin whose execute() returns a scripted CapabilityResult,
    keyed by capability, and records the request it received."""

    name = "fake"
    api_version = "1.0"
    supported = frozenset(Capability)

    def __init__(self, results=None, raises=None):
        self._results = results or {}
        self._raises = raises
        self.last_req: CapabilityRequest | None = None
        self._resources = ["t_users", "t_orders"]
        self._schema = {"fields": {"id": "integer", "email": "text"}}

    async def connect(self, dsn, options): ...
    async def health(self):
        return True

    async def close(self): ...
    def validate_request(self, req): ...

    async def execute(self, req):
        self.last_req = req
        if self._raises is not None:
            raise self._raises
        return self._results.get(req.capability, CapabilityResult())

    async def schema(self, resource, sample_size=None):
        return self._schema

    async def list_resources(self):
        return self._resources


@pytest.mark.asyncio
async def test_read_maps_to_legacy_find_shape():
    rows = [{"id": 1}, {"id": 2}]
    plugin = FakePlugin({Capability.READ: CapabilityResult(rows=rows)})
    adapter = CapabilityExecutorAdapter(plugin)

    out = await adapter.execute("t_users", Action.FIND, {"limit": 2, "skip": 0})

    # Mongo-style keys preserved for backward compat; neutral aliases added
    # (Risk #3): `rows` mirrors `documents`, plus a `_neutral` marker.
    assert {"documents", "skip", "limit", "count", "next_skip", "has_more"} <= set(out.keys())
    assert out["documents"] == rows
    assert out["rows"] == rows  # neutral alias present
    assert out["documents"] is out["rows"] or out["documents"] == out["rows"]
    assert out["_neutral"] is True
    assert out["count"] == 2
    assert out["skip"] == 0
    assert out["limit"] == 2
    assert out["next_skip"] == 2
    assert out["has_more"] is True  # count == limit

    # Request translation carried filter/limit/skip into the CapabilityRequest.
    assert plugin.last_req.capability == Capability.READ
    assert plugin.last_req.resource == "t_users"
    # Risk #1: the concrete action flows via req.action (NOT options["_action"]).
    assert plugin.last_req.action == Action.FIND.value
    assert "_action" not in plugin.last_req.options


@pytest.mark.asyncio
async def test_read_has_more_false_when_under_limit():
    plugin = FakePlugin({Capability.READ: CapabilityResult(rows=[{"id": 1}])})
    adapter = CapabilityExecutorAdapter(plugin)
    out = await adapter.execute("t", Action.FIND, {"limit": 20})
    assert out["has_more"] is False


@pytest.mark.asyncio
async def test_count_maps_to_int():
    plugin = FakePlugin({Capability.COUNT: CapabilityResult(scalar=42)})
    adapter = CapabilityExecutorAdapter(plugin)
    out = await adapter.execute("t", Action.COUNT, {"filter": {}})
    assert out == 42
    assert isinstance(out, int)


@pytest.mark.asyncio
async def test_insert_one_maps_to_inserted_id():
    plugin = FakePlugin({Capability.WRITE_ONE: CapabilityResult(affected=1, meta={"lastrowid": 7})})
    adapter = CapabilityExecutorAdapter(plugin)
    out = await adapter.execute("t", Action.INSERT_ONE, {"document": {"x": 1}})
    assert out["inserted_id"] == 7
    assert out["affected"] == 1  # neutral field (Risk #3)
    assert out["_neutral"] is True
    assert plugin.last_req.action == Action.INSERT_ONE.value


@pytest.mark.asyncio
async def test_insert_many_maps_to_inserted_count():
    plugin = FakePlugin({Capability.WRITE_MANY: CapabilityResult(affected=3)})
    adapter = CapabilityExecutorAdapter(plugin)
    out = await adapter.execute(
        "t", Action.INSERT_MANY, {"documents": [{"x": 1}, {"x": 2}, {"x": 3}]}
    )
    assert out["inserted_count"] == 3
    assert out["inserted_ids"] == []
    assert out["affected"] == 3
    assert out["_neutral"] is True


@pytest.mark.asyncio
async def test_update_one_maps_to_matched_modified():
    plugin = FakePlugin({Capability.WRITE_ONE: CapabilityResult(affected=2)})
    adapter = CapabilityExecutorAdapter(plugin)
    out = await adapter.execute(
        "t", Action.UPDATE_ONE, {"filter": {"id": 1}, "update": {"$set": {"a": 1}}}
    )
    assert out["matched"] == 2
    assert out["modified"] == 2
    assert out["affected"] == 2
    assert out["_neutral"] is True
    # req.action distinguishes update from insert under the same WRITE_ONE cap.
    assert plugin.last_req.action == Action.UPDATE_ONE.value


@pytest.mark.asyncio
async def test_update_many_maps_to_matched_modified():
    plugin = FakePlugin({Capability.WRITE_MANY: CapabilityResult(affected=5)})
    adapter = CapabilityExecutorAdapter(plugin)
    out = await adapter.execute(
        "t", Action.UPDATE_MANY, {"filter": {}, "update": {"$set": {"a": 1}}}
    )
    assert out["matched"] == 5
    assert out["modified"] == 5
    assert out["affected"] == 5
    assert out["_neutral"] is True


@pytest.mark.asyncio
async def test_delete_maps_to_deleted():
    plugin = FakePlugin({Capability.DELETE_ONE: CapabilityResult(affected=1)})
    adapter = CapabilityExecutorAdapter(plugin)
    out = await adapter.execute("t", Action.DELETE_ONE, {"filter": {"id": 1}})
    assert out["deleted"] == 1
    assert out["affected"] == 1
    assert out["_neutral"] is True


@pytest.mark.asyncio
async def test_list_collections_delegates_to_list_resources():
    plugin = FakePlugin()
    adapter = CapabilityExecutorAdapter(plugin)
    out = await adapter.list_collections()
    assert out == ["t_users", "t_orders"]


@pytest.mark.asyncio
async def test_collection_schema_returns_fields_dict():
    plugin = FakePlugin()
    adapter = CapabilityExecutorAdapter(plugin)
    out = await adapter.collection_schema("t_users", mask_fields=[])
    # Returns the raw {col: type} dict (pipeline wraps it in {"fields": ...}).
    assert out == {"id": "integer", "email": "text"}


@pytest.mark.asyncio
async def test_collection_schema_masks_named_fields():
    plugin = FakePlugin()
    adapter = CapabilityExecutorAdapter(plugin)
    out = await adapter.collection_schema("t_users", mask_fields=["email"])
    assert out["email"] == "masked"
    assert out["id"] == "integer"


@pytest.mark.asyncio
async def test_indexes_returns_rows_list():
    rows = [{"name": "pk", "key": [("id", 1)]}]
    plugin = FakePlugin({Capability.INDEXES: CapabilityResult(rows=rows)})
    adapter = CapabilityExecutorAdapter(plugin)
    out = await adapter.collection_indexes("t")
    assert out == rows


@pytest.mark.asyncio
async def test_list_databases_returns_rows():
    rows = [{"name": "appdb"}]
    plugin = FakePlugin({Capability.LIST_DATABASES: CapabilityResult(rows=rows)})
    adapter = CapabilityExecutorAdapter(plugin)
    out = await adapter.execute("", Action.LIST_DATABASES, {})
    assert out == rows


@pytest.mark.asyncio
async def test_explain_maps_to_plan():
    rows = [{"Plan": "Seq Scan"}]
    plugin = FakePlugin({Capability.EXPLAIN: CapabilityResult(rows=rows)})
    adapter = CapabilityExecutorAdapter(plugin)
    out = await adapter.execute("t", Action.EXPLAIN, {"filter": {}})
    assert out == {"plan": rows}


@pytest.mark.asyncio
async def test_enforce_index_is_noop():
    adapter = CapabilityExecutorAdapter(FakePlugin())
    assert await adapter.enforce_index_for_find("t", {"x": 1}) is None


def test_sanitize_error_is_generic():
    adapter = CapabilityExecutorAdapter(FakePlugin())
    msg = adapter.sanitize_error(ValueError("secret table public.users does not exist"))
    assert "secret" not in msg
    assert msg == "Operation failed. Check parameters and try again."


@pytest.mark.asyncio
async def test_guard_error_propagates_for_pipeline_to_catch():
    # The adapter does NOT swallow GuardError — it re-raises so the pipeline's
    # try/except Exception in _execute_and_build catches it and produces
    # {status: error} via sanitize_error.
    plugin = FakePlugin(raises=GuardValidationError("injection attempt"))
    adapter = CapabilityExecutorAdapter(plugin)
    with pytest.raises(GuardValidationError):
        await adapter.execute("t", Action.FIND, {})


@pytest.mark.asyncio
async def test_adapter_through_real_pipeline_yields_error_status(tmp_path):
    """End-to-end: a plugin GuardError surfaces as {status: error} from the
    pipeline (not a raw traceback / leaked message)."""
    from guardmcp.core.approval.store import ApprovalStore
    from guardmcp.core.audit.logger import AuditLogger
    from guardmcp.core.pipeline import GuardPipeline
    from guardmcp.core.policy.engine import PolicyEngine
    from guardmcp.core.policy.loader import PolicyLoader
    from guardmcp.core.risk.engine import RiskEngine

    pf = tmp_path / "policy.yaml"
    pf.write_text(
        "agent: a\nmode: readonly\ncollections:\n  allow: [t]\nactions:\n  allow: [find]\n"
    )
    loader = PolicyLoader(pf)
    loader.load()

    plugin = FakePlugin(raises=GuardValidationError("raw injection detail"))
    adapter = CapabilityExecutorAdapter(plugin)
    pipe = GuardPipeline(
        policy_loader=loader,
        policy_engine=PolicyEngine(),
        risk_engine=RiskEngine(),
        audit_logger=AuditLogger(tmp_path / "audit.jsonl"),
        approval_store=ApprovalStore(timeout_seconds=1.0),
        executor=adapter,
    )
    out = await pipe.run("a", "t", Action.FIND, {})
    assert out["status"] == "error"
    assert "raw injection detail" not in out["reason"]
