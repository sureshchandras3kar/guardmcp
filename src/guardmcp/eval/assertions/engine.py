"""
Deterministic assertion engine for GuardMCP evals.

Checks actual pipeline output against expected results.
No LLM judgments — all assertions are exact or regex matches.
"""

import re
from typing import Any

from ..models import ExpectedResult

MASK_VALUE = "***masked***"


class AssertionEngine:
    def check(
        self,
        actual: dict[str, Any],
        expected: ExpectedResult,
        decision_status: str | None = None,
    ) -> list[str]:
        failures: list[str] = []

        if expected.decision is not None:
            failures += self._check_decision(decision_status, expected.decision.value)

        if expected.approval_required is not None:
            failures += self._check_approval_required(decision_status, expected.approval_required)

        if expected.status is not None:
            failures += self._check_status(actual, expected.status)

        if expected.reason_contains is not None:
            failures += self._check_reason_contains(actual, expected.reason_contains)

        if expected.reason_matches is not None:
            failures += self._check_reason_matches(actual, expected.reason_matches)

        if expected.masked_fields:
            failures += self._check_masked_fields(actual, expected.masked_fields)

        if expected.unmasked_fields:
            failures += self._check_unmasked_fields(actual, expected.unmasked_fields)

        if expected.data_count is not None:
            failures += self._check_data_count(actual, expected.data_count)

        if expected.data_contains:
            failures += self._check_data_contains(actual, expected.data_contains)

        if expected.error_contains is not None:
            failures += self._check_error_contains(actual, expected.error_contains)

        return failures

    # ── Decision ──────────────────────────────────────────────────────────────

    _DECISION_MAP = {
        "allow": "allowed",
        "deny": "denied",
        "approval_required": "approval_required",
    }

    def _check_decision(self, actual_status: str | None, expected: str) -> list[str]:
        expected_status = self._DECISION_MAP.get(expected, expected)
        if actual_status != expected_status:
            return [
                f"decision: expected '{expected}' → status='{expected_status}', "
                f"got '{actual_status}'"
            ]
        return []

    def _check_approval_required(self, actual_status: str | None, expected: bool) -> list[str]:
        is_approval = actual_status == "approval_required"
        if expected and not is_approval:
            return [f"approval_required: expected True, decision was '{actual_status}'"]
        if not expected and is_approval:
            return ["approval_required: expected False, but got approval_required"]
        return []

    # ── Status ────────────────────────────────────────────────────────────────

    def _check_status(self, actual: dict, expected: str) -> list[str]:
        got = actual.get("status")
        if got != expected:
            return [f"status: expected '{expected}', got '{got}'"]
        return []

    # ── Reason ────────────────────────────────────────────────────────────────

    def _check_reason_contains(self, actual: dict, substring: str) -> list[str]:
        reason = actual.get("reason") or ""
        if substring.lower() not in reason.lower():
            return [f"reason_contains: '{substring}' not in '{reason}'"]
        return []

    def _check_reason_matches(self, actual: dict, pattern: str) -> list[str]:
        reason = actual.get("reason") or ""
        if not re.search(pattern, reason, re.IGNORECASE):
            return [f"reason_matches: pattern '{pattern}' did not match '{reason}'"]
        return []

    # ── Masking ────────────────────────────────────────────────────────────────

    def _extract_documents(self, actual: dict) -> list[dict]:
        data = actual.get("data")
        if isinstance(data, dict) and "documents" in data:
            return data["documents"]
        if isinstance(data, list):
            return data
        return []

    def _get_nested(self, doc: dict, field: str) -> Any:
        """Dot-notation field access: 'contact.email' → doc['contact']['email']."""
        current: Any = doc
        for part in field.split("."):
            if not isinstance(current, dict):
                return None
            current = current.get(part)
        return current

    def _check_masked_fields(self, actual: dict, fields: list[str]) -> list[str]:
        docs = self._extract_documents(actual)
        if not docs:
            return []
        failures = []
        for field in fields:
            for i, doc in enumerate(docs):
                val = self._get_nested(doc, field)
                if val is not None and val != MASK_VALUE:
                    failures.append(
                        f"masked_fields: '{field}' in doc[{i}] not masked (got {val!r})"
                    )
        return failures

    def _check_unmasked_fields(self, actual: dict, fields: list[str]) -> list[str]:
        docs = self._extract_documents(actual)
        if not docs:
            return []
        failures = []
        for field in fields:
            for i, doc in enumerate(docs):
                val = self._get_nested(doc, field)
                if val == MASK_VALUE:
                    failures.append(f"unmasked_fields: '{field}' in doc[{i}] should NOT be masked")
        return failures

    # ── Data ──────────────────────────────────────────────────────────────────

    def _check_data_count(self, actual: dict, expected: int) -> list[str]:
        docs = self._extract_documents(actual)
        got = len(docs)
        if got != expected:
            return [f"data_count: expected {expected} documents, got {got}"]
        return []

    def _check_data_contains(self, actual: dict, expected_docs: list[dict]) -> list[str]:
        docs = self._extract_documents(actual)
        failures = []
        for expected_doc in expected_docs:
            found = any(self._doc_matches(doc, expected_doc) for doc in docs)
            if not found:
                failures.append(f"data_contains: no document matches {expected_doc}")
        return failures

    def _doc_matches(self, actual_doc: dict, expected_subset: dict) -> bool:
        return all(actual_doc.get(k) == v for k, v in expected_subset.items())

    # ── Error ─────────────────────────────────────────────────────────────────

    def _check_error_contains(self, actual: dict, substring: str) -> list[str]:
        if actual.get("status") == "error":
            reason = actual.get("reason") or ""
            if substring.lower() not in reason.lower():
                return [f"error_contains: '{substring}' not in error '{reason}'"]
        return []
