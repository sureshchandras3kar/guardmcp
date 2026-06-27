from enum import Enum


class GuardError(Exception):
    """Base class for all GuardMCP errors."""


class GuardValidationError(GuardError):
    """Request failed backend safety validation (injection, banned construct).

    Messages may contain raw backend detail and are SANITIZED before reaching a
    client (see pipeline._execute_and_build → executor.sanitize_error).
    """


class TypeMarshalError(GuardValidationError):
    """A filter value could not be coerced to a field's known BSON type.

    Unlike a generic GuardValidationError, the message is AGENT-FACING and safe
    to surface verbatim: it names the field, the expected type, and the
    extended-JSON escape hatch. The pipeline maps this to ErrorCode.TYPE_MISMATCH
    so a type mismatch fails loud instead of silently returning no rows. Lives in
    core (not the plugin) so the database-agnostic pipeline can catch it without
    importing a backend.
    """


class GuardExecutionError(GuardError):
    """Backend execution failed."""


class PluginError(GuardError):
    """Plugin registration/loading/version error."""


class PluginVersionError(PluginError): ...


class ErrorCode(str, Enum):
    """Canonical machine-readable error codes.

    This is a CORE concept: policy/pipeline stamp these codes onto denial
    decisions at the source so the server layer does not have to infer the
    code from a prose reason string. server/responses.py re-exports this for
    backward compatibility.

    FROZEN PUBLIC ENUM (semver). Within a major API version (CORE_API_MAJOR)
    every member here is a STABLE PUBLIC CONTRACT:

      * the string VALUE of each code is stable and is never renamed,
        renumbered, or removed,
      * new codes MAY be ADDED (additive, non-breaking),
      * removing or renaming a code is a BREAKING change reserved for a major
        version bump.

    Agents branch on these string codes; tests/unit/test_error_contract.py pins
    the exact current set so any accidental rename/removal fails CI. The current
    frozen codes are:

      POLICY_DENIED, APPROVAL_REQUIRED, APPROVAL_DECLINED, READONLY,
      COLLECTION_NOT_ALLOWED, ACTION_NOT_ALLOWED, VALIDATION, RATE_LIMITED,
      BACKEND_ERROR, UNSUPPORTED_CAPABILITY, NOT_FOUND, TYPE_MISMATCH.
    """

    POLICY_DENIED = "POLICY_DENIED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    APPROVAL_DECLINED = "APPROVAL_DECLINED"
    READONLY = "READONLY"
    COLLECTION_NOT_ALLOWED = "COLLECTION_NOT_ALLOWED"
    ACTION_NOT_ALLOWED = "ACTION_NOT_ALLOWED"
    VALIDATION = "VALIDATION"
    RATE_LIMITED = "RATE_LIMITED"
    BACKEND_ERROR = "BACKEND_ERROR"
    UNSUPPORTED_CAPABILITY = "UNSUPPORTED_CAPABILITY"
    NOT_FOUND = "NOT_FOUND"
    # A filter value cannot be coerced to the field's known BSON type
    # (e.g. a date field given an un-parseable string). Surfaced by the
    # MongoDB type-marshalling layer so a type mismatch fails loud instead
    # of silently returning an empty result set.
    TYPE_MISMATCH = "TYPE_MISMATCH"
