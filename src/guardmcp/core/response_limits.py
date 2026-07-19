"""Byte-budget response capping — distinct from (and layered on top of) the
existing doc-COUNT caps (`max_limit`/`SafeLimit`). A small number of large
documents (embedded arrays, long text/blob fields) can still blow a response
budget even when the doc count is small. This module is backend-agnostic:
it operates on already-serialized JSON-safe values, never a concrete backend
type — core/ never imports Mongo/SQL specifics.
"""

from __future__ import annotations

import json
from typing import Any

# Matches the official mongodb-mcp-server's default responseBytesLimit (1 MiB).
DEFAULT_MAX_RESPONSE_BYTES = 1_000_000

# Per-line cap for opaque text (e.g. log lines) — distinct budget from the
# overall response, since a single huge line (stack trace) can dominate.
DEFAULT_MAX_LINE_CHARS = 4_000


def cap_by_bytes(
    items: list[Any], max_bytes: int = DEFAULT_MAX_RESPONSE_BYTES
) -> tuple[list[Any], bool]:
    """Keep items (in order) until adding the next one would exceed max_bytes
    of JSON-serialized size. Returns (kept_items, truncated). An item larger
    than the ENTIRE budget by itself is dropped (never returns an empty list
    with truncated=False when items was non-empty and the budget is tiny)."""
    if not items:
        return items, False
    kept: list[Any] = []
    total = 0
    for item in items:
        size = len(json.dumps(item, default=str).encode())
        if kept and total + size > max_bytes:
            return kept, True
        if not kept and size > max_bytes:
            # Even the first item alone exceeds budget — drop it, signal truncation.
            return kept, True
        kept.append(item)
        total += size
    return kept, False


def cap_lines(
    lines: list[str],
    max_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    max_line_chars: int = DEFAULT_MAX_LINE_CHARS,
) -> tuple[list[str], bool]:
    """Truncate each line to max_line_chars (marked with an ellipsis), then cap
    the overall list to max_bytes. Returns (lines, truncated) — truncated is
    True if EITHER any single line was shortened OR the overall list was cut."""
    line_truncated = False
    shortened: list[str] = []
    for line in lines:
        if len(line) > max_line_chars:
            shortened.append(line[:max_line_chars] + "...[truncated]")
            line_truncated = True
        else:
            shortened.append(line)
    kept, bytes_truncated = cap_by_bytes(shortened, max_bytes)
    return kept, (line_truncated or bytes_truncated)
