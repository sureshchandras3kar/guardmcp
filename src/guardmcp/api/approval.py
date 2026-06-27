import hmac

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from ..core.approval.models import ApprovalRequest
from ..core.approval.store import ApprovalStore


class DecisionPayload(BaseModel):
    approved: bool


def build_approval_app(store: ApprovalStore, api_token: str = "") -> FastAPI:
    """
    Build the approval REST API.

    When api_token is set, all requests must include:
        X-Approval-Token: <token>

    Leave api_token empty only for stdio transport where the API binds to localhost
    and is not accessible from outside the host.
    """
    app = FastAPI(title="GuardMCP Approval API", version="0.1.0")

    # Health endpoints — no auth required (used by k8s liveness/readiness probes)
    @app.get("/health", tags=["health"])
    async def health() -> dict:
        """Liveness probe — returns 200 if process is running."""
        return {"status": "ok"}

    @app.get("/ready", tags=["health"])
    async def ready() -> dict:
        """
        Readiness probe — returns 200 if GuardMCP is ready to serve requests.
        For now same as health; future: ping MongoDB and check policy loaded.
        """
        return {"status": "ready"}

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
