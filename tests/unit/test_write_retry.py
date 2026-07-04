"""S-8: writes get a single attempt; reads get retried on transient errors."""

import pytest
from pymongo.errors import AutoReconnect

from guardmcp.core.models.domain import WRITE_ACTIONS, Action
from guardmcp.plugins.mongodb.executor import MongoExecutor


def test_write_actions_membership():
    assert Action.INSERT_ONE in WRITE_ACTIONS
    assert Action.UPDATE_MANY in WRITE_ACTIONS
    assert Action.DELETE_MANY in WRITE_ACTIONS
    assert Action.DROP in WRITE_ACTIONS

    assert Action.FIND not in WRITE_ACTIONS
    assert Action.COUNT not in WRITE_ACTIONS
    assert Action.AGGREGATE not in WRITE_ACTIONS


class _CountingCollection:
    """Minimal collection that raises AutoReconnect, counting each attempt."""

    def __init__(self, counter):
        self.name = "things"
        self._counter = counter

    def find(self, *args, **kwargs):
        self._counter["count"] += 1
        raise AutoReconnect("boom")

    async def delete_one(self, *args, **kwargs):
        self._counter["count"] += 1
        raise AutoReconnect("boom")

    # enforce_index_for_find calls index_information when enforcement is on;
    # enforcement is off by default, so this is never reached for find.


class _FakeClient:
    def __init__(self, counter):
        self._col = _CountingCollection(counter)

    def get_collection(self, name, database=None):
        return self._col


async def test_read_action_retries_max_retries_plus_one():
    counter = {"count": 0}
    executor = MongoExecutor(_FakeClient(counter), max_retries=2, retry_base_delay=0)
    with pytest.raises(AutoReconnect):
        await executor.execute("things", Action.FIND, {"filter": {}})
    # max_retries=2 -> max_attempts = 3
    assert counter["count"] == 3


async def test_write_action_attempted_exactly_once():
    counter = {"count": 0}
    executor = MongoExecutor(_FakeClient(counter), max_retries=2, retry_base_delay=0)
    with pytest.raises(AutoReconnect):
        await executor.execute("things", Action.DELETE_ONE, {"filter": {"x": 1}})
    assert counter["count"] == 1


async def test_execute_once_call_counts_via_monkeypatch():
    """Same property, but isolated at the _execute_once boundary."""
    executor = MongoExecutor(object(), max_retries=2, retry_base_delay=0)

    calls = {"n": 0}

    async def fake_execute_once(collection, action, params, database=None):
        calls["n"] += 1
        raise AutoReconnect("boom")

    executor._execute_once = fake_execute_once

    calls["n"] = 0
    with pytest.raises(AutoReconnect):
        await executor.execute("c", Action.DELETE_ONE, {})
    assert calls["n"] == 1

    calls["n"] = 0
    with pytest.raises(AutoReconnect):
        await executor.execute("c", Action.FIND, {})
    assert calls["n"] == 3
