"""Stable public contract for the Users module."""

from ..application.session_service import (
    AuthenticatedUserView,
    SESSION_RETENTION_DAYS,
    SESSION_TOUCH_INTERVAL,
    USER_SESSION_MAX_AGE,
    UserSessionValidationError,
    UserSessionView,
    as_utc,
    cleanup_expired_user_sessions_state,
    create_user_session_state,
    hash_session_token,
    resolve_user_session_state,
    revoke_session_state,
    revoke_user_sessions_state,
    validate_user_session_state,
)
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
    "AuthenticatedUserView",
    "SESSION_RETENTION_DAYS",
    "SESSION_TOUCH_INTERVAL",
    "USER_SESSION_MAX_AGE",
    "UserSessionValidationError",
    "UserSessionView",
    "as_utc",
    "cleanup_expired_user_sessions_state",
    "create_user_session_state",
    "hash_session_token",
    "resolve_user_session_state",
    "revoke_session_state",
    "revoke_user_sessions_state",
    "validate_user_session_state",
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
