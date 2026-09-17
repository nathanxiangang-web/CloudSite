"""Plugin registry — loads, isolates, and exposes enabled plugins."""
from __future__ import annotations

import importlib
import logging
import os
from dataclasses import dataclass, field

from fastapi import APIRouter

from .base import Plugin

logger = logging.getLogger(__name__)


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

    def load_plugin(self, module_path: str) -> Plugin | None:
        """Import ``module_path`` and instantiate its ``plugin`` object.

        Returns ``None`` and logs a warning on any failure so that a
        broken or missing plugin never crashes the host application.
        """
        try:
            mod = importlib.import_module(module_path)
            plugin: Plugin = mod.plugin  # type: ignore[attr-defined]
            self._plugins[plugin.name] = plugin
            logger.info("plugin loaded: %s v%s", plugin.name, plugin.version)
            return plugin
        except Exception as exc:  # noqa: BLE001
            logger.warning("plugin failed to load (%s): %s", module_path, exc)
            return None

    def load_enabled(self) -> None:
        """Load all plugins whose ``ENABLE_<NAME>_PLUGIN`` env var is truthy.

        Plugin module paths are declared in the ``_BUILTIN_PLUGINS`` dict.
        Additional plugins can be registered by appending to this dict
        before calling ``load_enabled``.
        """
        for name, module_path in _BUILTIN_PLUGINS.items():
            env_var = f"ENABLE_{name.upper()}_PLUGIN"
            if os.getenv(env_var, "true").lower() in ("true", "1", "yes"):
                self.load_plugin(module_path)
            else:
                logger.info("plugin disabled by config: %s", name)

    def get_routers(self) -> list[APIRouter]:
        """Aggregate routers from all loaded plugins."""
        routers: list[APIRouter] = []
        for plugin in self._plugins.values():
            try:
                routers.extend(plugin.get_routers())
            except Exception as exc:  # noqa: BLE001
                logger.warning("plugin %s get_routers failed: %s", plugin.name, exc)
        return routers


_BUILTIN_PLUGINS: dict[str, str] = {
    "ai": "cloudsite.plugins.ai",
}