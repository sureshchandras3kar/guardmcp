"""
Transport lifecycle regression tests.

Root cause covered here: the low-level MCP ``Server.run`` enters the FastMCP
``lifespan`` on EVERY invocation. Under the streamable-http (and sse) transport
the session manager calls ``app.run`` **once per client session**, so any
lifespan whose teardown closes process-global resources (the shared Mongo
client, the policy loader, the approval store) tears them down when a single
session ends — breaking every subsequent session with pymongo's
``InvalidOperation: Cannot use MongoClient after close``.

stdio calls ``Server.run`` exactly once for the whole process, so the bug never
surfaced there.

* ``test_session_lifespan_does_not_close_shared_client`` — fast, deterministic,
  no real mongod. Emulates pymongo's "raise after close" contract and asserts a
  single MCP session lifecycle does not tear down the shared client / policy.
* ``test_streamable_http_db_tool_survives_session_boundary`` — full end-to-end:
  boots ``python -m guardmcp --transport streamable-http`` against a local
  MongoDB and asserts a DB tool succeeds over the HTTP session, including a
  second session opened after the first one is terminated.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from guardmcp.__main__ import build
from guardmcp.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]
PYTHON = sys.executable


class _AfterCloseError(RuntimeError):
    """Mirrors pymongo's InvalidOperation('Cannot use MongoClient after close')."""


def _patch_raise_after_close(monkeypatch):
    """Install a MongoClient stub that refuses use after ``close()`` — exactly
    like pymongo's async client. Lets us prove the lifespan-close bug without a
    real mongod and without depending on motor's sync-client reconnect quirk."""

    class _RaiseAfterCloseClient:
        def __init__(self, uri, database, *, min_pool_size=0, max_pool_size=100):
            self._closed = False

        def _check(self):
            if self._closed:
                raise _AfterCloseError("Cannot use MongoClient after close")

        def get_collection(self, name):
            self._check()
            return object()

        def get_db(self):
            self._check()
            return object()

        async def list_collection_names(self):
            self._check()
            return []

        async def list_databases(self):
            self._check()
            return [{"name": "test", "sizeOnDisk": 0}]

        async def ping(self):
            self._check()
            return True

        def close(self):
            self._closed = True

    monkeypatch.setattr("guardmcp.__main__.MongoClient", _RaiseAfterCloseClient)
    return _RaiseAfterCloseClient


async def test_session_lifespan_does_not_close_shared_client(tmp_path, monkeypatch):
    """A single MCP session (one Server.run lifespan cycle) must NOT close the
    process-global Mongo client or tear down the policy loader."""
    _patch_raise_after_close(monkeypatch)
    (tmp_path / "policy.yaml").write_text("agent: default-agent\nmode: readonly\n")
    settings = Settings(
        policy_path=tmp_path / "policy.yaml",
        audit_log_path=tmp_path / "audit.jsonl",
    )
    mcp, _rest, ctx = build(settings)

    client = ctx.registry.get("default").client
    server = mcp._mcp_server

    # Simulate ONE streamable-http session opening and then ending: the low-level
    # server enters and exits the (per-session) lifespan.
    async with server.lifespan(server):
        await client.ping()  # healthy inside the session

    # A subsequent session must still be able to use the shared client. On the
    # buggy code the lifespan teardown ran registry.close_all(), so this raises.
    await client.ping()
    assert await client.list_collection_names() == []
    # And the policy loader must not have been torn down.
    assert ctx.pipeline._policies.all(), "policy loader was torn down by a per-session lifespan"


# ── End-to-end over the real streamable-http transport ───────────────────────


def _mongo_available(host="127.0.0.1", port=27017) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_port(port: int, timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.2)
    raise TimeoutError(f"server did not open port {port} within {timeout}s")


async def _call_db_tool(url: str, tool: str, args: dict, *, terminate: bool):
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(url, terminate_on_close=terminate) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool, args)
            text = result.content[0].text if result.content else "{}"
            return result.isError, json.loads(text)


@pytest.mark.asyncio
async def test_streamable_http_db_tool_survives_session_boundary(tmp_path):
    if not _mongo_available():
        pytest.skip("no local MongoDB on 127.0.0.1:27017")

    policy = tmp_path / "policy.yaml"
    policy.write_text(
        "agent: default-agent\n"
        "mode: readonly\n"
        "collections:\n  allow: ['*']\n"
        "actions:\n  allow: [find, count, aggregate, explain, list_collections,"
        " list_databases, list_connections, collection_schema, collection_indexes, db_stats]\n"
    )
    port = _free_port()
    env = {
        **os.environ,
        "GUARDMCP_APPROVAL_ALLOW_INSECURE": "true",
        "GUARDMCP_TRANSPORT": "streamable-http",
        "GUARDMCP_MONGODB_URI": "mongodb://127.0.0.1:27017",
        "GUARDMCP_MONGODB_DATABASE": "test",
        "GUARDMCP_POLICY_PATH": str(policy),
        "GUARDMCP_AUDIT_LOG_PATH": str(tmp_path / "audit.jsonl"),
        "GUARDMCP_APPROVAL_PORT": str(_free_port()),
        "FASTMCP_PORT": str(port),
        "FASTMCP_HOST": "127.0.0.1",
    }
    proc = subprocess.Popen(
        [PYTHON, "-m", "guardmcp", "--transport", "streamable-http"],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{port}/mcp"
    try:
        _wait_for_port(port)
        # Session 1 — succeeds, then terminates (ends a session server-side).
        is_err, payload = await _call_db_tool(url, "mongodb_list_collections", {}, terminate=True)
        assert not is_err and payload["ok"] is True, payload

        await asyncio.sleep(1.0)  # let the terminated session unwind server-side

        # Session 2 — a DB tool must STILL succeed after the first session ended.
        is_err, payload = await _call_db_tool(url, "mongodb_list_collections", {}, terminate=False)
        assert not is_err and payload["ok"] is True, payload
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
