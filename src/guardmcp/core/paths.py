"""Cross-platform, dependency-free resolution of per-user state/log dirs.

The audit log must NOT default to a cwd-relative path: stdio MCP launches
(Claude Desktop, etc.) frequently set cwd=/ , so a relative ``logs/audit.jsonl``
would try to write to ``/logs/audit.jsonl`` (root) and silently fail or pollute
the repo when run from a checkout. Instead we resolve to a platform-approved
per-user state/log directory, always as an ABSOLUTE path.

Explicit operator overrides (an absolute ``GUARDMCP_AUDIT_LOG_PATH``, e.g. a
Docker volume mount) bypass all of this — see ``resolve_audit_path``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

__all__ = [
    "default_state_dir",
    "default_audit_log_path",
    "resolve_audit_path",
]


def default_state_dir(app: str = "guardmcp") -> Path:
    """Return the OS-appropriate per-user state/log directory for ``app``.

    - Windows: ``%LOCALAPPDATA%\\<app>\\logs`` (fallback ``~/AppData/Local/<app>/logs``).
    - macOS:   ``~/Library/Logs/<app>``.
    - Linux/other POSIX: ``$XDG_STATE_HOME/<app>`` if set, else ``~/.local/state/<app>``.

    Container note: a deployment may set ``XDG_STATE_HOME=/var/lib/...`` (or
    similar) — on POSIX that is honored here so the state dir follows the
    container's conventions without needing the absolute audit override.
    """
    if os.name == "nt" or sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        base = Path(local) if local else Path.home() / "AppData" / "Local"
        return base / app / "logs"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / app
    # Linux / other POSIX: follow the XDG Base Directory spec.
    xdg_state = os.environ.get("XDG_STATE_HOME")
    base = Path(xdg_state) if xdg_state else Path.home() / ".local" / "state"
    return base / app


def default_audit_log_path(app: str = "guardmcp") -> Path:
    """Default absolute audit log path: ``<state_dir>/audit.jsonl``."""
    return default_state_dir(app) / "audit.jsonl"


def resolve_audit_path(configured: Path, app: str = "guardmcp") -> Path:
    """Resolve the configured audit path to a final ABSOLUTE path.

    - If ``configured`` is already absolute, it is returned unchanged — the
      operator/Docker controls the exact location (e.g. a mounted volume at
      ``/var/log/guardmcp/audit.jsonl``).
    - If ``configured`` is relative (or empty), it is resolved against
      ``default_state_dir()`` — NOT the current working directory. This means a
      stray relative path can never land in ``/`` or the repo checkout, even
      when stdio launches with cwd=/.
    """
    configured = Path(configured)
    if configured.is_absolute():
        return configured
    state_dir = default_state_dir(app)
    # An empty/"." configured path means "use the default file name".
    if str(configured) in ("", "."):
        return state_dir / "audit.jsonl"
    return state_dir / configured
