"""admin/presentation 路由：站点呈现配置管理。"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ...auth import validate_request_origin
from ...modules.presentation.contracts.public import (
    PresentationConfig,
    PresentationPresetUnknown,
    PresentationRevisionNotFound,
    apply_admin_preset,
    get_admin_presentation,
    rollback_admin_presentation,
    save_admin_presentation,
    toggle_admin_presentation,
)
from ..home import invalidate_home_cache

router = APIRouter()


class ThemeTokensInput(BaseModel):
    accent_color: str = Field(
        default="#2563eb",
        pattern=r"^#[0-9a-fA-F]{6}$",
    )
    card_radius: int = Field(default=12, ge=0, le=32)


class NavigationItemInput(BaseModel):
    label: str = Field(min_length=1, max_length=40)
    href: str = Field(min_length=1, max_length=200)
    sort_order: int = 0


class HomeBlockInput(BaseModel):
    type: Literal[
        "featured",
        "recent",
        "topic",
        "category",
        "continue",
    ]
    enabled: bool = True
    sort_order: int = 0
    limit: int = Field(default=6, ge=1, le=24)
    title: str = Field(default="", max_length=60)


class PresentationUpdate(BaseModel):
    preset: Literal["software", "tutorial", "custom"] = "custom"
    theme_tokens: ThemeTokensInput = Field(
        default_factory=ThemeTokensInput
    )
    navigation: list[NavigationItemInput] = Field(
        default_factory=list,
        max_length=20,
    )
    home_blocks: list[HomeBlockInput] = Field(
        default_factory=list,
        max_length=12,
    )
    summary: str = Field(default="", max_length=200)


class ApplyPresetInput(BaseModel):
    preset: Literal["software", "tutorial"]


class RollbackInput(BaseModel):
    revision_id: int


class ToggleInput(BaseModel):
    enabled: bool


def _translate_presentation_error(
    exc: Exception,
) -> HTTPException:
    if isinstance(exc, PresentationPresetUnknown):
        return HTTPException(
            400,
            {
                "code": "PRESET_UNKNOWN",
                "message": f"未知预设：{exc.preset}",
            },
        )
    if isinstance(exc, PresentationRevisionNotFound):
        return HTTPException(
            404,
            {
                "code": "REVISION_NOT_FOUND",
                "message": "历史配置不存在",
            },
        )
    return HTTPException(
        500,
        {
            "code": "PRESENTATION_ERROR",
            "message": "站点呈现服务错误",
        },
    )


@router.get("/api/admin/presentation")
async def get_presentation():
    from ...main import StateSession

    async with StateSession() as state:
        return await get_admin_presentation(state)


@router.put("/api/admin/presentation")
async def save_presentation(
    payload: PresentationUpdate,
    request: Request,
):
    from ...main import StateSession

    validate_request_origin(request)
    cfg = PresentationConfig(
        preset=payload.preset,
        theme_tokens=payload.theme_tokens.model_dump(),
        navigation=[
            item.model_dump()
            for item in payload.navigation
        ],
        home_blocks=[
            block.model_dump()
            for block in payload.home_blocks
        ],
    )
    async with StateSession() as state:
        result = await save_admin_presentation(
            state,
            cfg=cfg,
            summary=payload.summary,
        )
    invalidate_home_cache()
    return result


@router.post("/api/admin/presentation/apply-preset")
async def apply_preset(
    payload: ApplyPresetInput,
    request: Request,
):
    from ...main import StateSession

    validate_request_origin(request)
    async with StateSession() as state:
        try:
            result = await apply_admin_preset(
                state,
                preset_id=payload.preset,
            )
        except PresentationPresetUnknown as exc:
            raise _translate_presentation_error(exc) from exc
    invalidate_home_cache()
    return result


@router.post("/api/admin/presentation/rollback")
async def rollback_presentation(
    payload: RollbackInput,
    request: Request,
):
    from ...main import StateSession

    validate_request_origin(request)
    async with StateSession() as state:
        try:
            result = await rollback_admin_presentation(
                state,
                revision_id=payload.revision_id,
            )
        except PresentationRevisionNotFound as exc:
            raise _translate_presentation_error(exc) from exc
    invalidate_home_cache()
    return result


@router.put("/api/admin/presentation/toggle")
async def toggle_presentation(
    payload: ToggleInput,
    request: Request,
):
    from ...main import StateSession

    validate_request_origin(request)
    async with StateSession() as state:
        result = await toggle_admin_presentation(
            state,
            enabled=payload.enabled,
        )
    invalidate_home_cache()
    return result
