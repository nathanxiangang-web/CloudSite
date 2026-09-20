"""T1 团队角色管理 schemas."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

_ROLE = Literal["viewer", "editor", "reviewer", "operator", "owner"] if False else str


class UserRoleResponse(BaseModel):
    user_id: int
    username: str
    role: str
    status: str


class UserRoleListResponse(BaseModel):
    users: list[UserRoleResponse]


class UpdateUserRoleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str = Field(min_length=1, max_length=20)


class RolePermissionsResponse(BaseModel):
    role: str
    can_edit_content: bool
    can_publish: bool
    can_review_submissions: bool
    can_manage_collections: bool
    can_manage_system: bool
    can_manage_users: bool
    can_manage_delivery: bool
    can_view_admin_dashboard: bool


class RoleListResponse(BaseModel):
    roles: list[str]
    permissions: list[RolePermissionsResponse]