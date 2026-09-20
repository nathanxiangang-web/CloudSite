"""CloudSite plugin system.

Plugins provide optional features that can be enabled or disabled via
environment variables.  A plugin exposes a narrow contract: a name, a
version, and a list of FastAPI routers to mount on the application.

Design goals (X3 spec):
- Plugin failures are isolated and never crash the host application.
- Disabling a plugin preserves existing content data.
- A default installation without any plugins is fully usable.
"""
from __future__ import annotations

from .base import Plugin
from .registry import PluginRegistry

__all__ = ["Plugin", "PluginRegistry"]