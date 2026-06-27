"""
Query cost estimation — the FROZEN, backend-neutral public contract.

A plugin estimates an operation's cost via its NATIVE explain (MongoDB explain,
SQL ``EXPLAIN``), then NORMALIZES the result into a :class:`CostEstimate` here.
The core never sees — and never exposes — the raw, backend-specific explain
output: only the normalized, bounded fields below. This keeps the public surface
database-agnostic and prevents leaking internal plan structure / data shapes.

``classify_cost`` is the SHARED heuristic that maps the normalized signals
(documents/rows examined, collection scan, index usage) to a single coarse
:class:`CostLevel`. Putting it here keeps the LOW/MEDIUM/HIGH/CRITICAL thresholds
identical across every backend (Mongo + the two SQL plugins) instead of each
backend inventing its own.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class CostLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"
    UNKNOWN = "UNKNOWN"


class CostEstimate(BaseModel):
    """Normalized, backend-neutral cost estimate.

    FROZEN public contract: this is the ONLY cost shape the core/tooling sees.
    No raw explain / plan output is ever carried here — only these bounded,
    normalized fields. All fields are optional (default None / UNKNOWN / []) so a
    backend that cannot estimate still returns a valid instance.
    """

    model_config = {"frozen": True}

    estimated_documents: int | None = None  # rows/docs scanned or returned
    estimated_keys_examined: int | None = None
    collection_scan: bool | None = None
    index_used: bool | None = None
    estimated_cost: CostLevel = CostLevel.UNKNOWN
    estimated_duration_ms: int | None = None
    warnings: list[str] = Field(default_factory=list)


# Heuristic thresholds (documented + shared). A collection/sequential scan is the
# dominant signal: scanning the whole table/collection is expensive regardless of
# size, so it floors the level at HIGH and goes CRITICAL once the scanned volume
# is large. An index-backed op touching few rows is LOW.
_HIGH_DOCS = 10_000  # scanned docs/rows at/above this is HIGH
_CRITICAL_DOCS = 1_000_000  # ... and at/above this is CRITICAL
_LOW_DOCS = 1_000  # below this, with an index, is LOW


def classify_cost(
    *,
    estimated_documents: int | None,
    collection_scan: bool | None,
    index_used: bool | None,
) -> CostLevel:
    """Map normalized signals → a single coarse CostLevel.

    Rules (in order):
      * No signal at all → UNKNOWN.
      * Collection/seq scan → at least HIGH; CRITICAL when the scanned volume is
        also large (``>= _CRITICAL_DOCS``).
      * Otherwise scale by scanned volume: ``>= _CRITICAL_DOCS`` → CRITICAL,
        ``>= _HIGH_DOCS`` → HIGH, ``< _LOW_DOCS`` → LOW, else MEDIUM.
      * An index-backed op touching few rows (``< _LOW_DOCS``) → LOW.
    """
    if estimated_documents is None and collection_scan is None and index_used is None:
        return CostLevel.UNKNOWN

    docs = estimated_documents

    if collection_scan:
        if docs is not None and docs >= _CRITICAL_DOCS:
            return CostLevel.CRITICAL
        return CostLevel.HIGH

    if docs is not None:
        if docs >= _CRITICAL_DOCS:
            return CostLevel.CRITICAL
        if docs >= _HIGH_DOCS:
            return CostLevel.HIGH
        if docs < _LOW_DOCS:
            return CostLevel.LOW
        return CostLevel.MEDIUM

    # No volume signal but we know an index is used → assume cheap; otherwise
    # we genuinely don't know.
    if index_used:
        return CostLevel.LOW
    return CostLevel.UNKNOWN
