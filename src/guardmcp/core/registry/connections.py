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


# Per-session active-database-per-connection map (set by db_use_database).
#
# Same Risk #8 isolation requirement as _active_connection above: this MUST be
# a ContextVar, not a field on the shared ConnectionEntry (which lives in the
# process-global registry dict and would leak a use_database() call across
# every concurrent session sharing that connection). Keyed by connection name
# so switching connections and back restores THAT connection's own remembered
# database, without requiring per-connection storage on the shared entry.
#
# default=None (not a mutable {}) — a shared mutable default is a ContextVar
# footgun even with disciplined copy-on-write elsewhere. get_active_database/
# set_active_database below always treat None as "no database set yet".
_active_databases: contextvars.ContextVar[dict[str, str] | None] = contextvars.ContextVar(
    "active_databases", default=None
)


def reset_active() -> None:
    """Reset the active connection AND active-database map for the CURRENT
    context back to defaults.

    Only affects the current contextvars.Context — a reset here is invisible to
    other requests running in their own copied contexts. Useful for explicit
    request teardown or tests that want a clean baseline.
    """
    _active_connection.set("default")
    _active_databases.set(None)


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

    def get_active_database(self) -> str | None:
        """Active database for the CURRENTLY ACTIVE connection, scoped to the
        CURRENT contextvars.Context (per-connection AND per-session — see
        _active_databases above). None if no entry is active or that
        connection never called set_active_database in this context."""
        entry = self.get_active()
        if entry is None:
            return None
        current = _active_databases.get()
        return current.get(self.active_name()) if current is not None else None

    def set_active_database(self, name: str | None) -> None:
        """Store the active database for the CURRENTLY ACTIVE connection, in
        THIS context only. No-op if no connection is currently active.

        Copy-on-write: never mutate the ContextVar's dict in place (it may be
        shared with a not-yet-diverged parent context) — always .set() a
        fresh dict.
        """
        entry = self.get_active()
        if entry is None:
            return
        current = _active_databases.get()
        updated = dict(current) if current is not None else {}
        updated[self.active_name()] = name
        _active_databases.set(updated)

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
