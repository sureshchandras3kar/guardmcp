"""Minimal in-process metrics registry — no external dependency
(no prometheus_client). A module-global counter dict, incremented by
GuardPipeline on every audit event, rendered as Prometheus text exposition
format by the approval API's `/metrics` endpoint.

Process-local only, same posture as the audit log's per-process HMAC chain
(see core/audit/logger.py Risk #5): each replica exposes its own counters,
there is no cross-replica aggregation here.
"""

from __future__ import annotations

import threading

_lock = threading.Lock()
_counters: dict[tuple[str, ...], int] = {}


def increment(name: str, **labels: str) -> None:
    """Increment a named counter, keyed by name + sorted label=value pairs."""
    key = (name, *tuple(f'{k}="{v}"' for k, v in sorted(labels.items())))
    with _lock:
        _counters[key] = _counters.get(key, 0) + 1


def render_prometheus() -> str:
    """Render all counters in Prometheus text exposition format. Empty
    registry renders as an empty string (valid, scrapeable output)."""
    with _lock:
        snapshot = dict(_counters)
    by_name: dict[str, list[tuple[tuple[str, ...], int]]] = {}
    for key, value in snapshot.items():
        by_name.setdefault(key[0], []).append((key[1:], value))
    lines: list[str] = []
    for name in sorted(by_name):
        lines.append(f"# TYPE {name} counter")
        for label_parts, value in sorted(by_name[name]):
            label_str = "{" + ",".join(label_parts) + "}" if label_parts else ""
            lines.append(f"{name}{label_str} {value}")
    return "\n".join(lines) + ("\n" if lines else "")


def reset() -> None:
    """Test-only: clear all counters."""
    with _lock:
        _counters.clear()
