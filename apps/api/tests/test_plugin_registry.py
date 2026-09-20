"""P0-5: PluginRegistry unit tests + P1-14: plugin disabled integration test"""
from __future__ import annotations

import os
import sys
from unittest.mock import patch

import pytest


# === P0-5: PluginRegistry unit tests ===


def test_load_plugin_success():
    """load_plugin returns the plugin and registers it."""
    from cloudsite.plugins import PluginRegistry

    registry = PluginRegistry()
    result = registry.load_plugin("cloudsite.plugins.ai")
    assert result is not None
    assert result.name == "ai"
    assert result.version == "1.0.0"
    assert registry.is_loaded("ai")


def test_load_plugin_nonexistent_module():
    """load_plugin returns None for a nonexistent module without crashing."""
    from cloudsite.plugins import PluginRegistry

    registry = PluginRegistry()
    result = registry.load_plugin("cloudsite.plugins.nonexistent")
    assert result is None
    assert not registry.is_loaded("nonexistent")


def test_load_plugin_missing_plugin_attribute():
    """load_plugin returns None when module has no 'plugin' object."""
    from cloudsite.plugins import PluginRegistry

    registry = PluginRegistry()
    # Use a module that exists but has no 'plugin' attribute
    result = registry.load_plugin("cloudsite.plugins.base")
    assert result is None


def test_load_plugin_name_collision_warning(caplog):
    """Loading a plugin with the same name warns and replaces."""
    from cloudsite.plugins import PluginRegistry

    registry = PluginRegistry()
    registry.load_plugin("cloudsite.plugins.ai")
    with caplog.at_level("WARNING"):
        registry.load_plugin("cloudsite.plugins.ai")
    assert any("already loaded" in msg for msg in caplog.messages)


def test_load_enabled_with_env_true(monkeypatch):
    """load_enabled loads plugin when env var is true."""
    from cloudsite.plugins import PluginRegistry

    monkeypatch.setenv("ENABLE_AI_PLUGIN", "true")
    registry = PluginRegistry()
    registry.load_enabled()
    assert registry.is_loaded("ai")


def test_load_enabled_with_env_false(monkeypatch):
    """load_enabled skips plugin when env var is false."""
    from cloudsite.plugins import PluginRegistry

    monkeypatch.setenv("ENABLE_AI_PLUGIN", "false")
    registry = PluginRegistry()
    registry.load_enabled()
    assert not registry.is_loaded("ai")


def test_load_enabled_with_env_on(monkeypatch):
    """load_enabled loads plugin when env var is 'on'."""
    from cloudsite.plugins import PluginRegistry

    monkeypatch.setenv("ENABLE_AI_PLUGIN", "on")
    registry = PluginRegistry()
    registry.load_enabled()
    assert registry.is_loaded("ai")


def test_load_enabled_with_env_garbage(monkeypatch):
    """load_enabled treats unrecognized values as disabled."""
    from cloudsite.plugins import PluginRegistry

    monkeypatch.setenv("ENABLE_AI_PLUGIN", "maybe")
    registry = PluginRegistry()
    registry.load_enabled()
    assert not registry.is_loaded("ai")


def test_load_enabled_default(monkeypatch):
    """load_enabled defaults to enabled when env var is unset."""
    from cloudsite.plugins import PluginRegistry

    monkeypatch.delenv("ENABLE_AI_PLUGIN", raising=False)
    registry = PluginRegistry()
    registry.load_enabled()
    assert registry.is_loaded("ai")


def test_get_routers_returns_list():
    """get_routers returns a list of APIRouter."""
    from cloudsite.plugins import PluginRegistry

    registry = PluginRegistry()
    registry.load_plugin("cloudsite.plugins.ai")
    routers = registry.get_routers()
    assert isinstance(routers, list)
    assert len(routers) == 2


def test_get_routers_empty_registry():
    """get_routers returns empty list for empty registry."""
    from cloudsite.plugins import PluginRegistry

    registry = PluginRegistry()
    assert registry.get_routers() == []


def test_get_plugin_returns_loaded():
    """get_plugin returns the loaded plugin by name."""
    from cloudsite.plugins import PluginRegistry

    registry = PluginRegistry()
    registry.load_plugin("cloudsite.plugins.ai")
    plugin = registry.get_plugin("ai")
    assert plugin is not None
    assert plugin.name == "ai"


def test_get_plugin_returns_none_for_unknown():
    """get_plugin returns None for unknown name."""
    from cloudsite.plugins import PluginRegistry

    registry = PluginRegistry()
    assert registry.get_plugin("nonexistent") is None


def test_core_path_collision_warning(caplog):
    """get_routers warns when a plugin route collides with a core path."""
    from fastapi import APIRouter

    from cloudsite.plugins import PluginRegistry

    registry = PluginRegistry()
    registry.register_core_paths({"/api/health"})

    # Manually inject a fake plugin with a colliding route
    class FakePlugin:
        name = "fake"
        version = "0.1"
        def get_routers(self):
            r = APIRouter()

            @r.get("/api/health")
            def collide():
                return {"ok": True}
            return [r]

    registry._plugins["fake"] = FakePlugin()
    with caplog.at_level("WARNING"):
        registry.get_routers()
    assert any("collides" in msg for msg in caplog.messages)