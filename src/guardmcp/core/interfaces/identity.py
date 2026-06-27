"""
Principal (agent identity) resolution seam (Risk #7).

The runtime currently obtains the agent id from settings.agent (set by the
operator at startup) or, for HTTP transports behind a gateway, the
`X-GuardMCP-Agent` header. That header is trusted ONLY when a gateway in front
of GuardMCP authenticates the caller and sets it; GuardMCP does not itself verify
it. For a zero-trust deployment, supply a real PrincipalResolver (JWT, mTLS,
OIDC) via the composition layer (__main__) — it resolves the authenticated agent
id from transport material and returns None to DENY.

This module establishes the interface + a behavior-preserving default
(StaticPrincipalResolver). Wiring a custom resolver into the live request path is
done in __main__/server.tools without touching the pipeline.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class PrincipalResolver(Protocol):
    """Resolve the authenticated agent id for a request.

    `transport_hint` carries whatever the transport layer can offer (e.g. parsed
    headers, a verified JWT claims dict, a client-cert subject). Returns the
    agent id, or None to DENY the request (no trusted principal).
    """

    def resolve(self, transport_hint: dict) -> str | None: ...


class StaticPrincipalResolver:
    """Default resolver: always returns the operator-configured agent id.

    Preserves current behavior exactly — the agent is fixed at server startup
    (settings.agent) and not derived from the request. Swap for a JWT/mTLS
    resolver in the composition layer for zero-trust principal authentication.
    """

    def __init__(self, agent: str) -> None:
        self._agent = agent

    def resolve(self, transport_hint: dict) -> str | None:
        return self._agent
