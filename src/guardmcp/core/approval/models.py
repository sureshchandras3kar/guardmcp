from datetime import datetime
from typing import Any

from pydantic import BaseModel

from ..models.domain import RiskLevel


class ApprovalRequest(BaseModel):
    approval_id: str
    agent: str
    action: str
    collection: str
    risk: RiskLevel
    reason: str
    params: dict[str, Any]
    created_at: datetime
    status: str = "pending"  # pending | approved | denied
