"""T1 团队角色管理 admin 路由。

Registered under /api/admin/roles/ — automatically protected by
admin_session_middleware. Admin cookie holders have owner-level access
(向后兼容).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ...models import User, utcnow
from ...role_schemas import (
    RoleListResponse,
    RolePermissionsResponse,
    UpdateUserRoleRequest,
    UserRoleListResponse,
    UserRoleResponse,
)

router = APIRouter()


def _roles_service():
    from ...services import roles  # noqa: PLC0415

    return roles


@router.get("/api/admin/roles", response_model=RoleListResponse)
async def list_roles():
    service = _roles_service()
    all_roles = service.list_roles()
    perms = []
    for r in all_roles:
        p = service.get_permissions(r)
        perms.append(RolePermissionsResponse(
            role=r,
            can_edit_content=p.can_edit_content,
            can_publish=p.can_publish,
            can_review_submissions=p.can_review_submissions,
            can_manage_collections=p.can_manage_collections,
            can_manage_system=p.can_manage_system,
            can_manage_users=p.can_manage_users,
            can_manage_delivery=p.can_manage_delivery,
            can_view_admin_dashboard=p.can_view_admin_dashboard,
        ))
    return RoleListResponse(roles=all_roles, permissions=perms)


@router.get("/api/admin/roles/users", response_model=UserRoleListResponse)
async def list_user_roles():
    from ...main import StateSession
    from sqlalchemy import select

    async with StateSession() as state:
        result = await state.execute(select(User).order_by(User.id))
        users = result.scalars().all()
        return UserRoleListResponse(
            users=[
                UserRoleResponse(
                    user_id=u.id,
                    username=u.username,
                    role=u.role,
                    status=u.status,
                )
                for u in users
            ]
        )


@router.put("/api/admin/roles/users/{user_id}", response_model=UserRoleResponse)
async def update_user_role(user_id: int, body: UpdateUserRoleRequest):
    from ...main import StateSession

    service = _roles_service()
    try:
        service.validate_role(body.role)
    except service.RoleError as exc:
        raise HTTPException(400, {"code": "INVALID_ROLE", "message": str(exc)})

    async with StateSession() as state:
        user = await state.get(User, user_id)
        if not user or user.deleted_at is not None:
            raise HTTPException(404, {"code": "USER_NOT_FOUND", "message": "用户不存在"})
        user.role = body.role
        user.updated_at = utcnow()
        await state.commit()
        return UserRoleResponse(
            user_id=user.id,
            username=user.username,
            role=user.role,
            status=user.status,
        )