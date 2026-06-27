"""
Standard MCP tool response envelope + error taxonomy.

Every GuardMCP tool returns a JSON string in the shape:

    {"ok": bool, "data": <payload>|null, "error": {...}|null, "meta": {...}}

This gives agents ONE uniform channel for success and failure, with a stable
machine-readable error `code` they can branch on instead of parsing prose.
"""

from __future__ import annotations

import json
from typing import Any

# ErrorCode is a CORE concept (policy/pipeline stamp codes at the source).
# Re-exported here for backward compatibility — existing imports of
# `from ...server.responses import ErrorCode` keep working unchanged.
from ..core.interfaces.errors import ErrorCode

__all__ = ["ErrorCode", "ok", "err", "from_pipeline_result"]


def ok(data: Any, **meta: Any) -> str:
    """Success envelope. `data` carries the payload; `meta` is optional context."""
    return json.dumps(
        {"ok": True, "data": data, "error": None, "meta": meta},
        default=str,
    )


def err(
    code: ErrorCode | str,
    message: str,
    *,
    retryable: bool = False,
    suggested_action: str | None = None,
    **meta: Any,
) -> str:
    """Error envelope with a stable machine-readable `code`."""
    code_str = code.value if isinstance(code, ErrorCode) else str(code)
    return json.dumps(
        {
            "ok": False,
            "data": None,
            "error": {
                "code": code_str,
                "message": message,
                "retryable": retryable,
                "suggested_action": suggested_action,
            },
            "meta": meta,
        },
        default=str,
    )


_CAPABILITIES_HINT = "call guardmcp_capabilities to see permitted actions"


def _infer_denied_code(reason: str) -> ErrorCode:
    """Map a pipeline 'denied' reason string to a specific ErrorCode."""
    low = reason.lower()
    if "readonly" in low:
        return ErrorCode.READONLY
    if "not in the allowed list" in low or "not permitted" in low or "deny" in low:
        return ErrorCode.COLLECTION_NOT_ALLOWED
    if "action" in low:
        return ErrorCode.ACTION_NOT_ALLOWED
    if "no policy" in low:
        return ErrorCode.POLICY_DENIED
    return ErrorCode.POLICY_DENIED


def from_pipeline_result(result: dict[str, Any]) -> str:
    """
    Map a GuardPipeline result dict to the standard envelope.

    Pipeline shapes:
      {"status": "success", "data": ...}  -> ok(data)
      {"status": "denied",  "reason": ..., "code": ...} -> err(code, ...)
      {"status": "error",   "reason": ..., "code": ...} -> err(BACKEND_ERROR | RATE_LIMITED, ...)

    The pipeline now stamps an explicit `code` on denial/error results. When
    present it is used DIRECTLY (no substring matching). Substring inference is
    kept only as a fallback for older paths that omit `code`.
    """
    status = result.get("status")

    if status == "success":
        # #6: pass the backend-neutral accessors (rows/affected/scalar) through
        # into the envelope meta so a consumer can branch on them uniformly,
        # regardless of backend, without parsing the native `data` shape.
        neutral = result.get("neutral")
        if neutral:
            return ok(result.get("data"), neutral=neutral)
        return ok(result.get("data"))

    reason = result.get("reason", "operation failed")
    explicit = result.get("code")

    if status == "error":
        if explicit == ErrorCode.TYPE_MISMATCH.value:
            # A filter value did not match a field's known BSON type. This is a
            # client/agent error, not a transient backend failure: retrying the
            # SAME value will fail identically, so it is NOT retryable. Point the
            # agent at db_schema and the extended-JSON escape hatch.
            return err(
                explicit,
                reason,
                retryable=False,
                suggested_action=(
                    "call db_schema to see field types; pass typed values via "
                    '{"$date":"YYYY-MM-DD"} / {"$oid":"<24hex>"} / '
                    '{"$decimal":"<num>"}'
                ),
            )
        if explicit:
            return err(explicit, reason, retryable=True)
        if "rate limit" in reason.lower():
            return err(ErrorCode.RATE_LIMITED, reason, retryable=True)
        return err(ErrorCode.BACKEND_ERROR, reason, retryable=True)

    if status == "denied":
        low = reason.lower()
        # Prefer the explicit code from the source over fragile substring inference.
        code = explicit
        retryable = code == ErrorCode.RATE_LIMITED.value
        if code is None:
            if "declined by user" in low:
                return err(ErrorCode.APPROVAL_DECLINED, reason, retryable=False)
            if "rate limit" in low:
                return err(ErrorCode.RATE_LIMITED, reason, retryable=True)
            code = _infer_denied_code(reason)
        return err(
            code,
            reason,
            retryable=retryable,
            suggested_action=_CAPABILITIES_HINT,
        )

    # Unknown shape — surface as backend error rather than silently dropping.
    return err(ErrorCode.BACKEND_ERROR, reason, retryable=True)
