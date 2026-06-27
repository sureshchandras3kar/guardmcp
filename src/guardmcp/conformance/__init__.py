"""GuardMCP plugin conformance kit.

Reusable contract checks that any :class:`~guardmcp.core.interfaces.plugin.DatabasePlugin`
implementation must satisfy. Third-party plugin authors can run these against
their own plugin to verify it honours the core contract::

    from guardmcp.conformance import assert_plugin_conformant
    from my_pkg import MyPlugin

    def test_my_plugin_conformance():
        assert_plugin_conformant(MyPlugin())
"""

from .plugin_conformance import (
    assert_plugin_conformant,
    check_plugin_conformance,
)

__all__ = ["check_plugin_conformance", "assert_plugin_conformant"]
