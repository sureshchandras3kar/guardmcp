import pytest

from guardmcp.core.interfaces.capability import (
    WRITE_CAPS,
    Capability,
    CapabilityRequest,
    CapabilityResult,
)
from guardmcp.core.interfaces.errors import PluginVersionError
from guardmcp.core.interfaces.plugin import DatabasePlugin
from guardmcp.core.registry.registry import CORE_API_MAJOR, PluginRegistry


def test_capability_enum_members():
    expected = {
        "READ",
        "COUNT",
        "AGGREGATE",
        "WRITE_ONE",
        "WRITE_MANY",
        "DELETE_ONE",
        "DELETE_MANY",
        "SCHEMA",
        "INDEXES",
        "EXPLAIN",
        "ESTIMATE",
        "LIST_RESOURCES",
        "LIST_DATABASES",
        "STATS",
        "DDL_CREATE",
        "DDL_DESTROY",
    }
    assert {c.name for c in Capability} == expected
    assert Capability.READ.value == "read"
    assert Capability.ESTIMATE.value == "estimate"


def test_write_caps_membership():
    assert Capability.WRITE_ONE in WRITE_CAPS
    assert Capability.DELETE_MANY in WRITE_CAPS
    assert Capability.DDL_DESTROY in WRITE_CAPS
    assert Capability.READ not in WRITE_CAPS
    assert Capability.AGGREGATE not in WRITE_CAPS


def test_capability_request_roundtrip():
    req = CapabilityRequest(
        capability=Capability.READ,
        resource="users",
        filter={"a": 1},
        limit=10,
    )
    dumped = req.model_dump()
    rebuilt = CapabilityRequest(**dumped)
    assert rebuilt == req
    assert dumped["options"] == {}


def test_capability_result_roundtrip():
    res = CapabilityResult(rows=[{"x": 1}], affected=1, scalar=42, meta={"k": "v"})
    dumped = res.model_dump()
    rebuilt = CapabilityResult(**dumped)
    assert rebuilt == res
    assert CapabilityResult().rows == []


def test_database_plugin_is_abstract():
    with pytest.raises(TypeError):
        DatabasePlugin()  # type: ignore[abstract]


class _FakePlugin(DatabasePlugin):
    name = "fake"
    api_version = "1.0"
    supported = frozenset({Capability.READ})

    async def connect(self, dsn: str, options: dict) -> None: ...
    async def health(self) -> bool:
        return True

    async def close(self) -> None: ...
    async def execute(self, req: CapabilityRequest) -> CapabilityResult:
        return CapabilityResult()

    async def schema(self, resource: str, sample_size: int | None = None) -> dict:
        return {}

    async def list_resources(self) -> list[str]:
        return []

    def validate_request(self, req: CapabilityRequest) -> None: ...


def test_concrete_plugin_instantiates():
    plugin = _FakePlugin()
    assert plugin.name == "fake"
    assert plugin.cross_resource_refs(CapabilityRequest(capability=Capability.READ)) == set()


def test_registry_register_and_instantiate():
    reg = PluginRegistry()
    reg.register(_FakePlugin)
    assert "fake" in reg.names()
    instance = reg.instantiate("fake")
    assert isinstance(instance, _FakePlugin)


def test_registry_version_mismatch_raises():
    class _BadPlugin(_FakePlugin):
        name = "bad"
        api_version = f"{int(CORE_API_MAJOR) + 1}.0"

    reg = PluginRegistry()
    with pytest.raises(PluginVersionError):
        reg.register(_BadPlugin)
