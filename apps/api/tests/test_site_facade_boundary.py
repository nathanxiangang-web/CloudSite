"""Architecture guard for the app-level Site composition facade."""

from __future__ import annotations

import ast
import inspect

import cloudsite.site as site_facade


def test_site_facade_does_not_reclaim_orm_or_legacy_presentation():
    tree = ast.parse(inspect.getsource(site_facade))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            imported.add(module)

    assert not any(name.startswith("sqlalchemy") for name in imported)
    assert not any(name.endswith("models") for name in imported)
    assert not any("services.presentation" in name for name in imported)


def test_site_facade_routes_settings_through_site_contract():
    source = inspect.getsource(site_facade)
    assert "modules.site.contracts.public" in source
    assert "modules.providers.contracts.public" in source
    assert "modules.resources.contracts.public" in source
    assert "modules.presentation.contracts.public" in source
