"""T1 team role management routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ...modules.users.contracts.public import (
    RoleError,
    UserRoleNotFound,
    get_permissions,
    list_roles as list_role_names,
    list_user_role_views,
    set_user_role,
)
from ...role_schemas import (
    RoleListResponse,
    RolePermissionsResponse,
    UpdateUserRoleRequest,
    UserRoleListResponse,
    UserRoleResponse,
)

router = APIRouter()


@router.get("/api/admin/roles", response_model=RoleListResponse)
async def list_roles():
    roles = list_role_names()
    permissions = []
    for role in roles:
        item = get_permissions(role)
        permissions.append(
            RolePermissionsResponse(
                role=role,
                can_edit_content=item.can_edit_content,
                can_publish=item.can_publish,
                can_review_submissions=item.can_review_submissions,
                can_manage_collections=item.can_manage_collections,
                can_manage_system=item.can_manage_system,
                can_manage_users=item.can_manage_users,
                can_manage_delivery=item.can_manage_delivery,
                can_view_admin_dashboard=item.can_view_admin_dashboard,
            )
        )
    return RoleListResponse(
        roles=roles,
        permissions=permissions,
    )


@router.get(
    "/api/admin/roles/users",
    response_model=UserRoleListResponse,
)
async def list_user_roles():
    from ...main import StateSession

    async with StateSession() as state:
        users = await list_user_role_views(state)
    return UserRoleListResponse(
        users=[UserRoleResponse(**item) for item in users]
    )


@router.put(
    "/api/admin/roles/users/{user_id}",
    response_model=UserRoleResponse,
)
async def update_user_role(
    user_id: int,
    body: UpdateUserRoleRequest,
):
    from ...main import StateSession

    async with StateSession() as state:
        try:
            item = await set_user_role(
                state,
                user_id=user_id,
                role=body.role,
            )
        except RoleError as exc:
            raise HTTPException(
                400,
                {
                    "code": "INVALID_ROLE",
                    "message": str(exc),
                },
            ) from exc
        except UserRoleNotFound as exc:
            raise HTTPException(
                404,
                {
                    "code": "USER_NOT_FOUND",
                    "message": "用户不存在",
                },
            ) from exc
    return UserRoleResponse(**item)
