"""Regression: MongoClient.list_databases() called `for db in result` on the
awaited result of `self._client.list_databases()` — but the real Motor driver
returns a CommandCursor (awaitable-then-async-iterable via .to_list()/async
for), not a plain list. Every existing unit test used a hand-rolled fake
`_Client.list_databases()` returning a plain list directly, so this never got
exercised against the REAL MongoClient class at all — only caught by driving
the live-MongoDB verification suite against testcontainers.
"""

import pytest

from guardmcp.plugins.mongodb.client import MongoClient


class _FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    async def to_list(self, length=None):
        return self._docs


class _FakeMotorClient:
    def __init__(self, docs):
        self._docs = docs

    async def list_databases(self):
        # Real Motor: this coroutine resolves to a CommandCursor, not a list.
        return _FakeCursor(self._docs)


@pytest.mark.asyncio
async def test_list_databases_handles_command_cursor_not_plain_list():
    mc = MongoClient.__new__(MongoClient)  # skip __init__ (no real connection)
    mc._client = _FakeMotorClient([{"name": "a", "sizeOnDisk": 100}, {"name": "b"}])

    result = await mc.list_databases()

    assert result == [{"name": "a", "sizeOnDisk": 100}, {"name": "b", "sizeOnDisk": 0}]
