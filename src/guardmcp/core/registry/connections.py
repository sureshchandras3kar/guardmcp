"""
Connection registry for switch-connection support.
Each named connection maps to a backend client + database name.
A ContextVar tracks which connection is active for the current MCP session.

This module is DATABASE-AGNOSTIC: it never imports a concrete backend. The
client object is produced by an injected `client_factory` (supplied by the
composition layer in __main__), so a connection can be MongoDB, PostgreSQL,
MySQL, etc. without this core module knowing.
"""

from __future__ import annotations

import contextvars
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from ..interfaces.backend import Backend
    from ..interfaces.plugin import DatabasePlugin


@runtime_checkable
class ClosableClient(Protocol):
    """Minimal contract a connection client must satisfy."""

    def close(self) -> None: ...


# factory(uri, database, *, min_pool_size, max_pool_size) -> client
ClientFactory = Callable[..., ClosableClient]

# Per-session active connection name (set by mongodb_switch_connection tool).
#
# Risk #8 — isolation requirement: correctness under concurrent multi-agent
# transports REQUIRES each request to run in its own contextvars.Context (FastMCP
# copies the context per request). The ContextVar default is process-global; a
# switch() in one request must NOT leak to another request's context. This is the
# standard ContextVar guarantee — a value set inside one copy_context() run is
# invisible to another. Verified for stdio (single session). For SSE/streamable-
# http multi-session, the active connection MUST be request-scoped: ensure the
# transport runs each request inside its own copied context (FastMCP does), so
# switch() mutations stay confined to that request.
_active_connection: contextvars.ContextVar[str] = contextvars.ContextVar(
    "active_connection", default="default"
)


def reset_active() -> None:
    """Reset the active connection for the CURRENT context back to the default.

    Only affects the current contextvars.Context — a reset here is invisible to
    other requests running in their own copied contexts. Useful for explicit
    request teardown or tests that want a clean baseline.
    """
    _active_connection.set("default")


@dataclass
class ConnectionEntry:
    client: Any
    database: str
    executor: Backend | None = field(default=None)
    plugin: DatabasePlugin | None = field(default=None)
    # Per-connection backend options (pool size, ssl, schema, timeouts, ...).
    # Stored at build time so a later plugin.connect(dsn, options) can use them
    # without re-reading Settings. Empty for the default MongoDB path.
    options: dict[str, Any] = field(default_factory=dict)


class ConnectionRegistry:
    def __init__(self, client_factory: ClientFactory | None = None) -> None:
        self._registry: dict[str, ConnectionEntry] = {}
        self._client_factory = client_factory

    def register(
        self,
        name: str,
        uri: str,
        database: str,
        min_pool_size: int = 0,
        max_pool_size: int = 100,
    ) -> None:
        if self._client_factory is None:
            raise RuntimeError(
                "ConnectionRegistry has no client_factory; cannot build a client. "
                "Construct ConnectionRegistry(client_factory=...) with a backend factory."
            )
        client = self._client_factory(
            uri, database, min_pool_size=min_pool_size, max_pool_size=max_pool_size
        )
        self._registry[name] = ConnectionEntry(client=client, database=database)

    def get_active(self) -> ConnectionEntry | None:
        name = _active_connection.get()
        return self._registry.get(name)

    def get(self, name: str) -> ConnectionEntry | None:
        return self._registry.get(name)

    def switch(self, name: str) -> bool:
        """Switch active connection. Returns False if name not registered."""
        if name not in self._registry:
            return False
        _active_connection.set(name)
        return True

    def active_name(self) -> str:
        return _active_connection.get()

    def list_names(self) -> list[str]:
        return list(self._registry.keys())

    def close_all(self) -> None:
        import asyncio
        import inspect

        for entry in self._registry.values():
            close = getattr(entry.client, "close", None)
            if close is None:
                continue
            result = close()
            # Some backend clients (plugins) expose an async close(); drive it
            # to completion if we're not already inside a running loop. If a loop
            # is running, skip rather than risk a "loop already running" error —
            # the lifespan teardown handles plugin pools separately.
            if inspect.isawaitable(result):
                coro: Any = result
                try:
                    asyncio.get_running_loop()
                except RuntimeError:
                    asyncio.run(coro)
                else:
                    coro.close()
