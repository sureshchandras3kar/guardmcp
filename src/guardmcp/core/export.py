"""Bulk export to a local file — for reads too large to return inline.

CRITICAL invariant: this module NEVER touches a backend and NEVER decides what
data is safe to write. Callers (server/tools/export.py) MUST pass documents
that already went through GuardPipeline's normal masking path (the identical
`pipeline.run()` call db_find/db_aggregate use) — this module only serializes
whatever it's given and writes it to disk. It is data-agnostic and
backend-agnostic by construction (core/ never imports a concrete backend).
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any


def sweep_expired(export_dir: Path, ttl_seconds: float) -> int:
    """Delete export files older than ttl_seconds. Returns count removed.
    Best-effort: a file that errors mid-sweep (e.g. removed concurrently) is
    skipped, not raised — cleanup must never break an export call."""
    if not export_dir.exists():
        return 0
    now = time.time()
    removed = 0
    for f in export_dir.glob("*.json"):
        try:
            if now - f.stat().st_mtime > ttl_seconds:
                f.unlink()
                removed += 1
        except OSError:
            continue
    return removed


def write_export(export_dir: Path, documents: list[Any]) -> dict[str, Any]:
    """Write already-governed documents to a new export file and return a
    manifest — NEVER the data itself (defeats the purpose: export exists to
    avoid a huge inline response).

    The filename is a freshly generated UUID, never derived from user input
    (collection name, filter, agent id, ...) — there is no path-traversal
    surface because no caller-controlled string ever reaches the filesystem.
    """
    export_dir.mkdir(parents=True, exist_ok=True)
    export_id = str(uuid.uuid4())
    path = export_dir / f"{export_id}.json"
    payload = json.dumps(documents)
    path.write_text(payload)
    return {
        "export_id": export_id,
        "path": str(path),
        "document_count": len(documents),
        "size_bytes": len(payload.encode()),
    }
