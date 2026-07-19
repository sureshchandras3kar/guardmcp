import hmac
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel

from ..core.approval.models import ApprovalRequest
from ..core.approval.store import ApprovalStore
from ..core.metrics import render_prometheus

# A readiness probe returns (ready, detail). It must be best-effort and never
# raise; detail explains a not-ready state WITHOUT leaking secrets.
ReadinessProbe = Callable[[], Awaitable[tuple[bool, str]]]


class DecisionPayload(BaseModel):
    approved: bool


def build_approval_app(
    store: ApprovalStore,
    api_token: str = "",
    readiness: ReadinessProbe | None = None,
    allowed_hosts: list[str] | None = None,
) -> FastAPI:
    """
    Build the approval REST API.

    When api_token is set, all requests must include:
        X-Approval-Token: <token>

    Leave api_token empty only for stdio transport where the API binds to localhost
    and is not accessible from outside the host.

    ``readiness`` (optional) is an async probe returning ``(ready, detail)`` used
    by ``/readyz``: ready when policy is loaded AND the default backend is
    reachable. Probes must be best-effort (never raise) and must not leak secrets.
    """
    app = FastAPI(title="GuardMCP Approval API", version="0.1.0")

    # DNS-rebinding protection: reject requests whose Host header isn't on the
    # allow-list. Without this, a malicious web page can make the user's browser
    # resolve an attacker domain to 127.0.0.1 and POST to the approval API
    # (which approves CRITICAL writes). Starlette's TrustedHostMiddleware strips
    # the port and matches the host part. `["*"]` (or empty) disables it — only
    # for trusted reverse-proxy/ingress deployments that rewrite Host.
    if allowed_hosts and "*" not in allowed_hosts:
        from starlette.middleware.trustedhost import TrustedHostMiddleware

        app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(allowed_hosts))

    # Health endpoints — no auth required (used by k8s liveness/readiness probes).
    # /healthz + /readyz are the canonical names; /health + /ready are kept as
    # aliases for backward compatibility.
    @app.get("/healthz", tags=["health"])
    @app.get("/health", tags=["health"])
    async def healthz() -> dict:
        """Liveness probe — returns 200 if the process is up."""
        return {"status": "ok"}

    @app.get("/readyz", tags=["health"])
    @app.get("/ready", tags=["health"])
    async def readyz() -> JSONResponse:
        """
        Readiness probe — 200 when policy is loaded AND the default backend is
        reachable; 503 with a (secret-free) detail otherwise. With no probe
        wired it falls back to liveness (always ready).
        """
        if readiness is None:
            return JSONResponse({"status": "ready"})
        try:
            ready_ok, detail = await readiness()
        except Exception as exc:  # noqa: BLE001 - probe must never crash the endpoint
            return JSONResponse(
                {"status": "not_ready", "detail": f"readiness probe error: {exc!r}"},
                status_code=503,
            )
        if ready_ok:
            return JSONResponse({"status": "ready"})
        return JSONResponse({"status": "not_ready", "detail": detail}, status_code=503)

    @app.get("/metrics", tags=["health"])
    async def metrics_endpoint() -> PlainTextResponse:
        """Prometheus text-exposition metrics — no auth, same posture as the
        health endpoints (no PII/query content, just per-action/status
        request counters). Process-local only; see core/metrics.py."""
        return PlainTextResponse(
            render_prometheus(), media_type="text/plain; version=0.0.4"
        )

    def _verify_token(x_approval_token: str = Header(default="")) -> None:
        # S-2: constant-time comparison — plain != leaks token bytes via timing
        # on networked transports (sse/streamable-http), where this endpoint
        # approves CRITICAL writes.
        if api_token and not hmac.compare_digest(x_approval_token, api_token):
            raise HTTPException(status_code=403, detail="invalid or missing approval token")

    router = APIRouter(
        prefix="/approvals",
        tags=["approvals"],
        dependencies=[Depends(_verify_token)],
    )

    @router.get("/pending", response_model=list[ApprovalRequest])
    async def list_pending() -> list[ApprovalRequest]:
        return store.list_pending()

    @router.get("/{approval_id}", response_model=ApprovalRequest)
    async def get_approval(approval_id: str) -> ApprovalRequest:
        req = store.get(approval_id)
        if req is None:
            raise HTTPException(status_code=404, detail="approval not found")
        return req

    @router.post("/{approval_id}/decide")
    async def decide(approval_id: str, payload: DecisionPayload) -> dict:
        req = store.resolve(approval_id, approved=payload.approved)
        if req is None:
            raise HTTPException(status_code=404, detail="approval not found or already resolved")
        return {"approval_id": approval_id, "status": req.status}

    app.include_router(router)
    return app
