"""Architecture and ownership guards for user data."""

from __future__ import annotations

import ast
import inspect

import cloudsite.userdata as userdata_facade
from cloudsite.models import (
    UserFavorite as LegacyUserFavorite,
    UserPlaybackProgress as LegacyUserPlaybackProgress,
    UserResourceHistory as LegacyUserResourceHistory,
)
from cloudsite.modules.users.infrastructure.models import (
    UserFavorite as ModuleUserFavorite,
    UserPlaybackProgress as ModuleUserPlaybackProgress,
    UserResourceHistory as ModuleUserResourceHistory,
)


def test_userdata_models_are_users_owned():
    assert LegacyUserFavorite is ModuleUserFavorite
    assert LegacyUserResourceHistory is ModuleUserResourceHistory
    assert LegacyUserPlaybackProgress is ModuleUserPlaybackProgress


def test_userdata_facade_has_no_orm_or_shared_model_imports():
    tree = ast.parse(inspect.getsource(userdata_facade))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module or "")

    assert not any(
        name == "sqlalchemy" or name.startswith("sqlalchemy.")
        for name in imports
    )
    assert not any(name.endswith("models") for name in imports)

    source = inspect.getsource(userdata_facade)
    assert "shares.service" not in source
    assert "select(" not in source
    assert "delete(" not in source
    assert "Resource(" not in source
    assert "modules.users.contracts.public" in source
    assert "modules.resources.contracts.public" in source
    assert "modules.providers.contracts.public" in source
