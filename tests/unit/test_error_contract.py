"""
Stability lock for the FROZEN PUBLIC ErrorCode enum.

ErrorCode is a semver-public contract (see core/interfaces/errors.py): within a
major API version, code VALUES are never renamed/renumbered/removed; new codes
may be ADDED. This test pins the EXACT current set so any accidental rename or
removal fails CI. Adding a new code requires intentionally updating EXPECTED here.
"""

from guardmcp.core.interfaces.errors import ErrorCode

# Hard-coded expected set of (name, value) pairs. Do NOT loosen this to a
# derived comprehension — the whole point is that it is independent of the enum.
EXPECTED: set[tuple[str, str]] = {
    ("POLICY_DENIED", "POLICY_DENIED"),
    ("APPROVAL_REQUIRED", "APPROVAL_REQUIRED"),
    ("APPROVAL_DECLINED", "APPROVAL_DECLINED"),
    ("READONLY", "READONLY"),
    ("COLLECTION_NOT_ALLOWED", "COLLECTION_NOT_ALLOWED"),
    ("ACTION_NOT_ALLOWED", "ACTION_NOT_ALLOWED"),
    ("VALIDATION", "VALIDATION"),
    ("RATE_LIMITED", "RATE_LIMITED"),
    ("BACKEND_ERROR", "BACKEND_ERROR"),
    ("UNSUPPORTED_CAPABILITY", "UNSUPPORTED_CAPABILITY"),
    ("NOT_FOUND", "NOT_FOUND"),
    ("TYPE_MISMATCH", "TYPE_MISMATCH"),
    ("DATABASE_NOT_ALLOWED", "DATABASE_NOT_ALLOWED"),
}


def test_error_code_set_is_pinned():
    actual = {(member.name, member.value) for member in ErrorCode}
    assert actual == EXPECTED, (
        "ErrorCode is a FROZEN PUBLIC enum. Codes may be ADDED (update EXPECTED "
        "in this test) but never renamed/renumbered/removed within a major.\n"
        f"  added (in enum, not pinned): {actual - EXPECTED}\n"
        f"  removed (pinned, not in enum): {EXPECTED - actual}"
    )


def test_error_code_values_are_string_codes():
    for member in ErrorCode:
        assert isinstance(member.value, str)
        assert member.value == member.name
