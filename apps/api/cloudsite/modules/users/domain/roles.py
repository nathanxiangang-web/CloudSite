"""Users-owned role and permission policy."""

from __future__ import annotations

from dataclasses import dataclass

ROLE_VIEWER = "viewer"
ROLE_EDITOR = "editor"
ROLE_REVIEWER = "reviewer"
ROLE_OPERATOR = "operator"
ROLE_OWNER = "owner"

_ALL_ROLES = (
    ROLE_VIEWER,
    ROLE_EDITOR,
    ROLE_REVIEWER,
    ROLE_OPERATOR,
    ROLE_OWNER,
)
_ROLE_RANK = {role: index for index, role in enumerate(_ALL_ROLES)}


class RoleError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Permissions:
    can_edit_content: bool
    can_publish: bool
    can_review_submissions: bool
    can_manage_collections: bool
    can_manage_system: bool
    can_manage_users: bool
    can_manage_delivery: bool
    can_view_admin_dashboard: bool


_PERMISSIONS_BY_ROLE: dict[str, Permissions] = {
    ROLE_VIEWER: Permissions(
        can_edit_content=False,
        can_publish=False,
        can_review_submissions=False,
        can_manage_collections=False,
        can_manage_system=False,
        can_manage_users=False,
        can_manage_delivery=False,
        can_view_admin_dashboard=False,
    ),
    ROLE_EDITOR: Permissions(
        can_edit_content=True,
        can_publish=False,
        can_review_submissions=False,
        can_manage_collections=True,
        can_manage_system=False,
        can_manage_users=False,
        can_manage_delivery=True,
        can_view_admin_dashboard=True,
    ),
    ROLE_REVIEWER: Permissions(
        can_edit_content=True,
        can_publish=True,
        can_review_submissions=True,
        can_manage_collections=True,
        can_manage_system=False,
        can_manage_users=False,
        can_manage_delivery=True,
        can_view_admin_dashboard=True,
    ),
    ROLE_OPERATOR: Permissions(
        can_edit_content=True,
        can_publish=True,
        can_review_submissions=True,
        can_manage_collections=True,
        can_manage_system=True,
        can_manage_users=False,
        can_manage_delivery=True,
        can_view_admin_dashboard=True,
    ),
    ROLE_OWNER: Permissions(
        can_edit_content=True,
        can_publish=True,
        can_review_submissions=True,
        can_manage_collections=True,
        can_manage_system=True,
        can_manage_users=True,
        can_manage_delivery=True,
        can_view_admin_dashboard=True,
    ),
}


def validate_role(role: str) -> str:
    if role not in _ALL_ROLES:
        raise RoleError(f"Invalid role: {role}")
    return role


def get_permissions(role: str) -> Permissions:
    if role not in _PERMISSIONS_BY_ROLE:
        raise RoleError(f"Invalid role: {role}")
    return _PERMISSIONS_BY_ROLE[role]


def has_permission(role: str, permission: str) -> bool:
    perms = get_permissions(role)
    return getattr(perms, permission, False)


def role_at_least(role: str, minimum: str) -> bool:
    if role not in _ROLE_RANK or minimum not in _ROLE_RANK:
        return False
    return _ROLE_RANK[role] >= _ROLE_RANK[minimum]


def is_admin_role(role: str) -> bool:
    return role in (
        ROLE_EDITOR,
        ROLE_REVIEWER,
        ROLE_OPERATOR,
        ROLE_OWNER,
    )


def get_admin_permissions() -> Permissions:
    return _PERMISSIONS_BY_ROLE[ROLE_OWNER]


def list_roles() -> list[str]:
    return list(_ALL_ROLES)


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
