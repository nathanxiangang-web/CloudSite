"""Stable public contract for the Users module."""

from ..application.reference_queries import (
    UserReferenceView,
    user_references,
)
from ..application.role_management import (
    UserRoleNotFound,
    list_user_role_views,
    set_user_role,
)
from ..domain.roles import (
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
    "UserReferenceView",
    "user_references",
    "UserRoleNotFound",
    "list_user_role_views",
    "set_user_role",
    "Permissions",
    "RoleError",
    "get_admin_permissions",
    "get_permissions",
    "has_permission",
    "is_admin_role",
    "list_roles",
    "role_at_least",
    "validate_role",
]
