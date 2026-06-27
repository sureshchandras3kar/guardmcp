"""
MySQL-specific request validation.

Backend-specific guard knowledge lives in the plugin (mirroring the MongoDB
plugin's guard.py and the PostgreSQL plugin's validate.py). These checks run
BEFORE translation/execution and reject anything that cannot be expressed as
safe, parameterized SQL.

The guard logic is shared with PostgreSQL in :mod:`plugins.sql.validate_base`;
this module is a thin shim that binds the MySQL ``quote_ident`` (backtick-quoted
identifiers) to the shared validators.
"""

from __future__ import annotations

from ...core.interfaces.capability import CapabilityRequest
from ..sql import validate_base
from .translate import quote_ident


def validate_request(req: CapabilityRequest) -> None:
    """Raise GuardValidationError if the request is unsafe for this backend."""
    validate_base.validate_request(req, quote_ident)


def cross_resource_refs(req: CapabilityRequest) -> set[str]:
    """Return foreign resources referenced by the request."""
    return validate_base.cross_resource_refs(req, quote_ident)
