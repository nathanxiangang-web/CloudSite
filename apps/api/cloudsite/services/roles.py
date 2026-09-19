"""Backward-compatible shim for Users role policy."""

from ..modules.users.domain.roles import (
    ROLE_EDITOR,
    ROLE_OPERATOR,
    ROLE_OWNER,
    ROLE_REVIEWER,
    ROLE_VIEWER,
    Permissions,
    RoleError,
    get_admin_permissions,
    get_permissions,
    has_permission,
    is_admin_role,
    list_roles,
    role_at_least,
    validate_role,
)

__all__ = [
    "ROLE_VIEWER",
    "ROLE_EDITOR",
    "ROLE_REVIEWER",
    "ROLE_OPERATOR",
    "ROLE_OWNER",
    "RoleError",
    "Permissions",
    "validate_role",
    "get_permissions",
    "has_permission",
    "role_at_least",
    "is_admin_role",
    "get_admin_permissions",
    "list_roles",
]
