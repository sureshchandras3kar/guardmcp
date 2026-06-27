"""Tests for the additive data-model fields and seams (Risks #1, #2, #10)."""

from guardmcp.core.interfaces.capability import (
    ACTION_TO_CAPABILITY,
    CAPABILITY_TO_ACTION,
    Capability,
    CapabilityRequest,
)
from guardmcp.core.interfaces.plugin import DatabasePlugin
from guardmcp.core.models.domain import Action


def test_capability_request_accepts_new_optional_fields():
    req = CapabilityRequest(
        capability=Capability.WRITE_ONE,
        resource="orders",
        action="update_one",
        sort={"created_at": -1},
        returning=["id", "status"],
        joins=[{"resource": "customers", "on": {"customer_id": "id"}}],
        tx_id="tx-123",
    )
    assert req.action == "update_one"
    assert req.sort == {"created_at": -1}
    assert req.returning == ["id", "status"]
    assert req.joins == [{"resource": "customers", "on": {"customer_id": "id"}}]
    assert req.tx_id == "tx-123"


def test_capability_request_new_fields_default_none():
    # Fully backward compatible: omitting the new fields leaves them None.
    req = CapabilityRequest(capability=Capability.READ, resource="t")
    assert req.action is None
    assert req.sort is None
    assert req.returning is None
    assert req.joins is None
    assert req.tx_id is None
    # No control key is smuggled through options by default.
    assert req.options == {}


def test_capability_to_action_round_trips_unambiguous_caps():
    # For unambiguous capabilities the reverse map must agree with the forward
    # ACTION_TO_CAPABILITY map.
    unambiguous = [
        Capability.READ,
        Capability.COUNT,
        Capability.AGGREGATE,
        Capability.EXPLAIN,
        Capability.SCHEMA,
        Capability.INDEXES,
        Capability.LIST_DATABASES,
        Capability.STATS,
        Capability.DELETE_ONE,
        Capability.DELETE_MANY,
    ]
    for cap in unambiguous:
        action_name = CAPABILITY_TO_ACTION[cap]
        action = Action(action_name)
        assert ACTION_TO_CAPABILITY[action] == cap


def test_capability_to_action_covers_every_capability_with_an_action():
    # Every capability that maps to a concrete operation has a reverse entry.
    # (Capability.LIST_RESOURCES has no Action equivalent and is intentionally
    # absent.)
    mapped_caps = set(ACTION_TO_CAPABILITY.values())
    for cap in mapped_caps:
        assert cap in CAPABILITY_TO_ACTION
        # The reverse value is always a valid Action name.
        assert Action(CAPABILITY_TO_ACTION[cap])


def test_ambiguous_write_caps_default_to_insert():
    assert CAPABILITY_TO_ACTION[Capability.WRITE_ONE] == Action.INSERT_ONE.value
    assert CAPABILITY_TO_ACTION[Capability.WRITE_MANY] == Action.INSERT_MANY.value


class _MinimalPlugin(DatabasePlugin):
    """Concrete plugin overriding only the abstract methods — exercises the
    default transaction seam."""

    name = "minimal"
    api_version = "1.0"
    supported = frozenset({Capability.READ})

    async def connect(self, dsn, options): ...
    async def health(self):
        return True

    async def close(self): ...
    async def execute(self, req): ...  # type: ignore[override]
    async def schema(self, resource, sample_size=None):
        return {}

    async def list_resources(self):
        return []

    def validate_request(self, req): ...


def test_database_plugin_default_transaction_seam():
    p = _MinimalPlugin()
    assert p.supports_transactions is False


async def test_database_plugin_begin_returns_none_by_default():
    p = _MinimalPlugin()
    assert await p.begin() is None
    # commit/rollback are no-ops that must not raise.
    assert await p.commit("tx") is None
    assert await p.rollback("tx") is None
