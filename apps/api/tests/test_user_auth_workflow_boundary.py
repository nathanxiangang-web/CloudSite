"""Architecture guard for the public-auth HTTP edge."""

from __future__ import annotations

import ast
import inspect

import cloudsite.auth as auth_facade


def test_auth_facade_has_no_user_orm_or_sql_queries():
    tree = ast.parse(inspect.getsource(auth_facade))
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

    source = inspect.getsource(auth_facade)
    assert "OperationLog" not in source
    assert "select(" not in source
    assert "session.get(User" not in source
    assert "modules.users.contracts.public" in source


def test_auth_facade_keeps_http_compatibility_helpers():
    assert callable(auth_facade.validate_username)
    assert callable(auth_facade.validate_password)
    assert callable(auth_facade.verify_password)
    assert callable(auth_facade.user_dict)
    assert hasattr(auth_facade, "password_hash")
