from __future__ import annotations

from importlib.metadata import entry_points

from ..interfaces.errors import PluginError, PluginVersionError
from ..interfaces.plugin import DatabasePlugin

CORE_API_MAJOR = "1"

ENTRY_POINT_GROUP = "guardmcp.plugins"


def _check_version(plugin_cls: type[DatabasePlugin]) -> None:
    """Raise PluginVersionError if the plugin's api_version major != CORE_API_MAJOR."""
    api_version = getattr(plugin_cls, "api_version", None)
    if api_version is None:
        raise PluginVersionError(f"Plugin {plugin_cls!r} declares no api_version")
    major = str(api_version).split(".", 1)[0]
    if major != CORE_API_MAJOR:
        raise PluginVersionError(
            f"Plugin {getattr(plugin_cls, 'name', plugin_cls.__name__)!r} api_version "
            f"{api_version!r} (major {major}) is incompatible with core API major "
            f"{CORE_API_MAJOR!r}"
        )


class PluginRegistry:
    """Registry of DatabasePlugin classes keyed by their declared ``name``."""

    def __init__(self) -> None:
        self._plugins: dict[str, type[DatabasePlugin]] = {}

    def register(self, plugin_cls: type[DatabasePlugin]) -> None:
        """Register a plugin class after validating its API version."""
        if not (isinstance(plugin_cls, type) and issubclass(plugin_cls, DatabasePlugin)):
            raise PluginError(f"{plugin_cls!r} is not a DatabasePlugin subclass")
        name = getattr(plugin_cls, "name", None)
        if not name:
            raise PluginError(f"Plugin {plugin_cls!r} declares no name")
        _check_version(plugin_cls)
        self._plugins[name] = plugin_cls

    def discover(self) -> None:
        """Discover plugins advertised via the ``guardmcp.plugins`` entry-point group."""
        for ep in entry_points(group=ENTRY_POINT_GROUP):
            plugin_cls = ep.load()
            self.register(plugin_cls)

    def instantiate(self, name: str) -> DatabasePlugin:
        """Instantiate a registered plugin by name."""
        try:
            plugin_cls = self._plugins[name]
        except KeyError:
            raise PluginError(f"No plugin registered under name {name!r}") from None
        return plugin_cls()

    def names(self) -> list[str]:
        return list(self._plugins)

    def manifest(self, type_name: str) -> dict:
        """#7: return a registered plugin's manifest from its CLASS, WITHOUT
        instantiate()/connect() (works even if the backend's optional driver
        isn't installed)."""
        try:
            plugin_cls = self._plugins[type_name]
        except KeyError:
            raise PluginError(f"No plugin registered under name {type_name!r}") from None
        return plugin_cls.manifest()

    def manifests(self) -> dict[str, dict]:
        """#7: manifests for every registered plugin, keyed by name. Read from
        classes only — no instantiation or connection."""
        return {name: cls.manifest() for name, cls in self._plugins.items()}
