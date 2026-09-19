"""Architecture guard for administrator user HTTP edge."""

from __future__ import annotations

import ast
import inspect

import cloudsite.users as users_facade


def test_admin_users_facade_has_no_user_orm_or_sql_queries():
    tree = ast.parse(inspect.getsource(users_facade))
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

    source = inspect.getsource(users_facade)
    assert "OperationLog" not in source
    assert "select(" not in source
    assert "password_hash" not in source
    assert "modules.users.contracts.public" in source


def test_admin_users_facade_does_not_borrow_auth_business_helpers():
    source = inspect.getsource(users_facade)
    assert "validate_username" not in source
    assert "validate_password" not in source
    assert "user_dict" not in source
    assert "auth_error" not in source
