"""Reusable conformance checks for GuardMCP DatabasePlugin implementations.

Third-party plugin authors:
    from guardmcp.conformance import check_plugin_conformance
    def test_my_plugin():
        check_plugin_conformance(MyPlugin())

All checks are STATIC — they never call ``connect()`` and never touch a live
database. They assert that a plugin instance honours the structural contract
declared by :class:`~guardmcp.core.interfaces.plugin.DatabasePlugin`:

* it is a ``DatabasePlugin`` subclass instance
* it declares a non-empty ``name`` (str), an ``api_version`` (str) whose MAJOR
  matches the core API major, and a non-empty ``supported`` frozenset of
  :class:`~guardmcp.core.interfaces.capability.Capability`
* every abstract method is overridden and callable, and ``cross_resource_refs``
  is present
* ``validate_request`` is callable and does not crash on a normal request
* ``cross_resource_refs`` returns a ``set`` for a normal request

For SQL-style backends where resource names map to real identifiers, the caller
can opt in to an additional injection-rejection check by passing
``expects_identifier_validation=True``: a request carrying a clearly-invalid
identifier (``"x; DROP TABLE y"``) must raise
:class:`~guardmcp.core.interfaces.errors.GuardValidationError`. This is OFF by
default so document-store backends (e.g. MongoDB, where collection names are
arbitrary strings) are not falsely failed.
"""

from __future__ import annotations

from typing import Any

from ..core.interfaces.capability import (
    Capability,
    CapabilityRequest,
)
from ..core.interfaces.errors import GuardValidationError
from ..core.interfaces.plugin import DatabasePlugin
from ..core.registry.registry import CORE_API_MAJOR

# Methods that DatabasePlugin declares abstract and a plugin MUST override.
_ABSTRACT_METHODS = (
    "connect",
    "health",
    "close",
    "execute",
    "schema",
    "list_resources",
    "validate_request",
)

# A read-style capability to use when probing validate_request / cross_resource_refs.
# Prefer READ; fall back to any supported capability so non-READ backends still work.
_PROBE_PREFERENCE = (
    Capability.READ,
    Capability.COUNT,
    Capability.LIST_RESOURCES,
)

# An obviously-malicious identifier that a SQL-style backend must reject.
_INJECTION_RESOURCE = "x; DROP TABLE y"


def _pick_probe_capability(supported: Any) -> Capability | None:
    if not supported:
        return None
    for cap in _PROBE_PREFERENCE:
        if cap in supported:
            return cap
    # Otherwise just use any supported capability.
    for cap in supported:
        if isinstance(cap, Capability):
            return cap
    return None


def check_plugin_conformance(
    plugin: DatabasePlugin,
    *,
    expects_identifier_validation: bool = False,
) -> list[str]:
    """Return a list of conformance failure strings (empty == conformant).

    Args:
        plugin: an instantiated DatabasePlugin (do NOT pass the class).
        expects_identifier_validation: when True, additionally assert that
            ``validate_request`` rejects an injection-style resource identifier
            with ``GuardValidationError``. Use for SQL-style backends where the
            resource maps to a real identifier; leave False for backends with
            opaque/arbitrary resource names (e.g. MongoDB collections).
    """
    failures: list[str] = []

    # ── isinstance ───────────────────────────────────────────────────────────
    if not isinstance(plugin, DatabasePlugin):
        failures.append(
            f"plugin {plugin!r} is not a DatabasePlugin instance "
            f"(did you pass the class instead of an instance?)"
        )
        # Without the base contract, the rest is meaningless.
        return failures

    # ── name ─────────────────────────────────────────────────────────────────
    name = getattr(plugin, "name", None)
    if not isinstance(name, str) or not name:
        failures.append(f"name must be a non-empty str, got {name!r}")

    # ── api_version ──────────────────────────────────────────────────────────
    api_version = getattr(plugin, "api_version", None)
    if not isinstance(api_version, str) or not api_version:
        failures.append(f"api_version must be a non-empty str, got {api_version!r}")
    else:
        major = api_version.split(".", 1)[0]
        if major != CORE_API_MAJOR:
            failures.append(
                f"api_version {api_version!r} major {major!r} != core API major {CORE_API_MAJOR!r}"
            )

    # ── supported ─────────────────────────────────────────────────────────────
    supported = getattr(plugin, "supported", None)
    if not isinstance(supported, frozenset):
        failures.append(f"supported must be a frozenset, got {type(supported).__name__}")
        supported = frozenset()
    elif not supported:
        failures.append("supported must be a non-empty frozenset of Capability")
    else:
        bad = [c for c in supported if not isinstance(c, Capability)]
        if bad:
            failures.append(f"supported contains non-Capability members: {bad!r}")

    # ── abstract methods overridden + callable ────────────────────────────────
    for meth in _ABSTRACT_METHODS:
        fn = getattr(plugin, meth, None)
        if fn is None or not callable(fn):
            failures.append(f"required method {meth!r} is missing or not callable")
        else:
            # Detect a method left at the ABC's abstract stub.
            base = getattr(DatabasePlugin, meth, None)
            owner = getattr(type(plugin), meth, None)
            if base is not None and owner is base:
                failures.append(f"abstract method {meth!r} is not overridden")

    # cross_resource_refs is concrete on the ABC (has a default) but must exist.
    crr = getattr(plugin, "cross_resource_refs", None)
    if crr is None or not callable(crr):
        failures.append("cross_resource_refs is missing or not callable")

    # ── runtime probes (no DB) ─────────────────────────────────────────────────
    probe_cap = _pick_probe_capability(supported)
    if probe_cap is not None:
        normal_req = CapabilityRequest(capability=probe_cap, resource="conformance_probe")

        # validate_request must be callable and not crash on a normal request.
        vfn = getattr(plugin, "validate_request", None)
        if callable(vfn):
            try:
                vfn(normal_req)
            except GuardValidationError:
                failures.append(
                    "validate_request rejected a normal request "
                    f"(capability={probe_cap.value}, resource='conformance_probe')"
                )
            except Exception as exc:  # noqa: BLE001 - report any crash as a failure
                failures.append(f"validate_request crashed on a normal request: {exc!r}")

        # cross_resource_refs must return a set for a normal request.
        if callable(crr):
            try:
                refs = crr(normal_req)
            except Exception as exc:  # noqa: BLE001
                failures.append(f"cross_resource_refs crashed on a normal request: {exc!r}")
            else:
                if not isinstance(refs, set):
                    failures.append(
                        f"cross_resource_refs must return a set, got {type(refs).__name__}"
                    )

        # Transaction seam (Risk #10): if a plugin advertises transaction
        # support, begin/commit/rollback must be genuinely overridden (callable
        # and not the ABC's no-op default). Tolerant by default: a plugin that
        # leaves supports_transactions False is never failed here.
        if getattr(plugin, "supports_transactions", False):
            for meth in ("begin", "commit", "rollback"):
                fn = getattr(plugin, meth, None)
                if fn is None or not callable(fn):
                    failures.append(
                        f"supports_transactions is True but {meth!r} is missing or not callable"
                    )
                    continue
                base = getattr(DatabasePlugin, meth, None)
                owner = getattr(type(plugin), meth, None)
                if base is not None and owner is base:
                    failures.append(
                        f"supports_transactions is True but {meth!r} is not "
                        f"overridden (still the no-op default)"
                    )

        # Optional: SQL-style identifier validation.
        if expects_identifier_validation and callable(vfn):
            inj_req = CapabilityRequest(capability=probe_cap, resource=_INJECTION_RESOURCE)
            try:
                vfn(inj_req)
            except GuardValidationError:
                pass  # correct: injection identifier rejected
            except Exception as exc:  # noqa: BLE001
                failures.append(
                    "validate_request raised a non-GuardValidationError on an "
                    f"injection identifier {_INJECTION_RESOURCE!r}: {exc!r}"
                )
            else:
                failures.append(
                    "validate_request accepted an injection identifier "
                    f"{_INJECTION_RESOURCE!r} (expected GuardValidationError)"
                )

    return failures


def assert_plugin_conformant(
    plugin: DatabasePlugin,
    *,
    expects_identifier_validation: bool = False,
) -> None:
    """Strict variant: raise AssertionError listing all conformance failures.

    Empty failure list == conformant (no error raised).
    """
    failures = check_plugin_conformance(
        plugin, expects_identifier_validation=expects_identifier_validation
    )
    if failures:
        plugin_name = getattr(plugin, "name", type(plugin).__name__)
        joined = "\n  - ".join(failures)
        raise AssertionError(f"Plugin {plugin_name!r} is not conformant:\n  - {joined}")
