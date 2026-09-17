"""Plugin registry — loads, isolates, and exposes enabled plugins."""
from __future__ import annotations

import importlib
import logging
import os
from dataclasses import dataclass, field

from fastapi import APIRouter

from .base import Plugin

logger = logging.getLogger(__name__)

_TRUE_VALUES = frozenset({"true", "1", "yes", "on", "y", "enable", "enabled"})
_FALSE_VALUES = frozenset({"false", "0", "no", "off", "n", "disable", "disabled", ""})

_DEFAULT_PLUGIN_SOURCES: dict[str, str] = {
    "ai": "cloudsite.plugins.ai",
}


@dataclass
class PluginRegistry:
    """Holds loaded plugins and aggregates their routers.

    Usage::

        registry = PluginRegistry()
        registry.load_enabled()
        for router in registry.get_routers():
            app.include_router(router)
    """

    _plugins: dict[str, Plugin] = field(default_factory=dict)
    _plugin_sources: dict[str, str] = field(default_factory=lambda: dict(_DEFAULT_PLUGIN_SOURCES))
    _core_paths: set[str] = field(default_factory=set)

    def register_core_paths(self, paths: set[str]) -> None:
        """Record core route paths for collision detection."""
        self._core_paths = paths

    def load_plugin(self, module_path: str) -> Plugin | None:
        """Import ``module_path`` and instantiate its ``plugin`` object.

        Returns ``None`` and logs a warning on any failure so that a
        broken or missing plugin never crashes the host application.
        """
        try:
            mod = importlib.import_module(module_path)
            plugin: Plugin = mod.plugin  # type: ignore[attr-defined]
            if plugin.name in self._plugins:
                logger.warning("plugin %s already loaded, replacing", plugin.name)
            self._plugins[plugin.name] = plugin
            logger.info("plugin loaded: %s v%s", plugin.name, plugin.version)
            return plugin
        except Exception as exc:  # noqa: BLE001
            logger.warning("plugin failed to load (%s): %s", module_path, exc, exc_info=True)
            return None

    def load_enabled(self) -> None:
        """Load all plugins whose ``ENABLE_<NAME>_PLUGIN`` env var is truthy.

        Plugin module paths are declared in ``_plugin_sources``.
        """
        for name, module_path in self._plugin_sources.items():
            env_var = f"ENABLE_{name.upper()}_PLUGIN"
            raw = os.getenv(env_var, "true").lower()
            if raw in _TRUE_VALUES:
                self.load_plugin(module_path)
            elif raw in _FALSE_VALUES:
                logger.info("plugin disabled by config: %s", name)
            else:
                logger.warning("plugin %s has unrecognized env value %s=%r, treating as disabled", name, env_var, raw)

    def get_routers(self) -> list[APIRouter]:
        """Aggregate routers from all loaded plugins with collision detection."""
        routers: list[APIRouter] = []
        for plugin in self._plugins.values():
            try:
                for router in plugin.get_routers():
                    self._check_collisions(plugin.name, router)
                    routers.append(router)
            except Exception as exc:  # noqa: BLE001
                logger.warning("plugin %s get_routers failed: %s", plugin.name, exc, exc_info=True)
        return routers

    def _check_collisions(self, plugin_name: str, router: APIRouter) -> None:
        """Warn if plugin routes collide with core paths."""
        for route in router.routes:
            if hasattr(route, "path"):
                if route.path in self._core_paths:
                    logger.warning(
                        "plugin %s route %s collides with a core path",
                        plugin_name, route.path,
                    )

    def is_loaded(self, name: str) -> bool:
        """Check whether a plugin is loaded."""
        return name in self._plugins

    def get_plugin(self, name: str) -> Plugin | None:
        """Return a loaded plugin by name, or None."""
        return self._plugins.get(name)
