"""
Dependency-free structured logging + trace-id correlation.

Replaces ad-hoc `print(..., file=sys.stderr)` calls across the codebase with a
single JSON-per-line event emitter. The same trace_id is stamped on structured
log lines AND the AuditRecord for a request, so a single operation can be
correlated across components.

Output is one JSON object per line on stderr:
    {"ts": "<iso>", "level": "...", "event": "...", "trace_id": "...", <fields>}

Level threshold is read from GUARDMCP_LOG_LEVEL (default "info"); ordering is
debug < info < warning < error. Format is read from GUARDMCP_LOG_FORMAT
(json | text); "text" emits the legacy human-readable line for local dev.
"""

from __future__ import annotations

import json
import os
import secrets
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

trace_id: ContextVar[str] = ContextVar("trace_id", default="")

_LEVELS = {"debug": 10, "info": 20, "warning": 30, "error": 40}

# #9: W3C traceparent — "00-<32hex trace>-<16hex span>-<2hex flags>".
_TRACEPARENT_VERSION = "00"
_ALL_ZERO_TRACE = "0" * 32
_ALL_ZERO_SPAN = "0" * 16


def parse_traceparent(header: str | None) -> str | None:
    """Parse a W3C `traceparent` header and return its 32-hex trace-id, or None
    if the header is missing/malformed. Only version 00 is recognised."""
    if not header or not isinstance(header, str):
        return None
    parts = header.strip().split("-")
    if len(parts) != 4:
        return None
    version, trace, span, flags = parts
    if version != _TRACEPARENT_VERSION:
        return None
    if len(trace) != 32 or len(span) != 16 or len(flags) != 2:
        return None
    try:
        int(trace, 16)
        int(span, 16)
        int(flags, 16)
    except ValueError:
        return None
    # The all-zero trace-id is invalid per the spec.
    if trace == _ALL_ZERO_TRACE or span == _ALL_ZERO_SPAN:
        return None
    return trace


def new_trace_id(incoming_traceparent: str | None = None) -> str:
    """Set the current trace id and return it.

    #9: when a valid inbound W3C `traceparent` is supplied, CONTINUE that trace
    (reuse its 32-hex trace-id) instead of minting a fresh one. Otherwise mint a
    new 32-hex (16-byte) trace-id. The id is always the W3C 32-hex form."""
    continued = parse_traceparent(incoming_traceparent)
    tid = continued if continued is not None else secrets.token_hex(16)
    trace_id.set(tid)
    return tid


def new_span_id() -> str:
    """Mint a fresh 16-hex (8-byte) span id."""
    return secrets.token_hex(8)


def current_traceparent() -> str:
    """Build a W3C `traceparent` from the current trace-id plus a fresh span.
    If no trace-id is set, one is minted first (sampled flag = 01)."""
    tid = get_trace_id()
    if not tid or len(tid) != 32:
        tid = new_trace_id()
    return f"{_TRACEPARENT_VERSION}-{tid}-{new_span_id()}-01"


def get_trace_id() -> str:
    """Return the current trace id (empty string if none set)."""
    return trace_id.get()


def _threshold() -> int:
    return _LEVELS.get(os.environ.get("GUARDMCP_LOG_LEVEL", "info").lower(), 20)


def _format() -> str:
    return os.environ.get("GUARDMCP_LOG_FORMAT", "json").lower()


def log_event(level: str, event: str, **fields) -> None:
    """Emit ONE structured log line to stderr if `level` meets the threshold."""
    lvl = _LEVELS.get(level.lower(), 20)
    if lvl < _threshold():
        return
    tid = get_trace_id()
    if _format() == "text":
        # Legacy human-readable line for local dev.
        detail = " ".join(f"{k}={v}" for k, v in fields.items())
        prefix = f"[guardmcp] {level.upper()} {event}"
        line = f"{prefix} {detail}".rstrip()
        print(line, file=sys.stderr)
        return
    record = {
        "ts": datetime.now(UTC).isoformat(),
        "level": level.lower(),
        "event": event,
        "trace_id": tid,
        # #9: a fresh span id per emitted event so log lines are individually
        # addressable within the trace.
        "span_id": new_span_id(),
        **fields,
    }
    print(json.dumps(record, default=str), file=sys.stderr)
