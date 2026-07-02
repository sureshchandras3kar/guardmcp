from __future__ import annotations

import re
from typing import Any

from .models import AmbiguityReport, Interpretation

# concept keyword -> candidate (field, operator, value) templates.
# Detection keeps only templates whose field exists in the collection schema.
_CONCEPTS: dict[str, list[tuple[str, str, Any]]] = {
    "active": [
        ("status", "=", "ACTIVE"),
        ("state", "=", "ACTIVE"),
        ("is_active", "=", True),
        ("active", "=", True),
        ("enabled", "=", True),
        ("account_enabled", "=", True),
    ],
    "inactive": [
        ("status", "=", "INACTIVE"),
        ("is_active", "=", False),
        ("enabled", "=", False),
        ("account_enabled", "=", False),
    ],
    "enabled": [("enabled", "=", True), ("account_enabled", "=", True), ("is_active", "=", True)],
    "disabled": [("enabled", "=", False), ("account_enabled", "=", False)],
}

_TOKEN_RE = re.compile(r"[a-z_]+")


class AmbiguityDetector:
    def detect(
        self, intent: str, schema_fields: dict[str, str], indexed_fields: set[str]
    ) -> AmbiguityReport:
        tokens = set(_TOKEN_RE.findall(intent.lower()))
        seen: set[tuple[str, str, str]] = set()
        survivors: list[Interpretation] = []
        for concept, templates in _CONCEPTS.items():
            if concept not in tokens:
                continue
            for field, op, value in templates:
                if field not in schema_fields:
                    continue
                dedup = (field, op, str(value))
                if dedup in seen:
                    continue
                seen.add(dedup)
                confidence = 0.5 + (0.1 if field in indexed_fields else 0.0)
                survivors.append(
                    Interpretation(
                        field=field,
                        operator=op,
                        value=value,
                        confidence=confidence,
                        evidence=f"concept '{concept}' maps to field '{field}' present in schema",
                    )
                )
        survivors.sort(key=lambda i: (-i.confidence, i.field))
        ambiguous = len(survivors) >= 2
        top = survivors[0].confidence if survivors else 1.0
        return AmbiguityReport(
            ambiguous=ambiguous,
            confidence=top if ambiguous else 1.0,
            interpretations=survivors,
            recommendation="Ask user for clarification." if ambiguous else "",
        )
