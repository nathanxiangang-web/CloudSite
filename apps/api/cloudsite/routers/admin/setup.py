"""admin/setup routes: one-shot initialization and setup wizard."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ...admin_auth import get_setup_completed, verify_setup_token
from ...auth import validate_request_origin
from ...config import settings
from ...modules.setup.contracts.public import (
    SetupWorkflowError,
    complete_initial_alist_setup,
    get_wizard_state,
    process_wizard_step,
    skip_wizard,
)
from ...schemas import AListInput

router = APIRouter()


def _origin_or_403(request: Request) -> None:
    try:
        validate_request_origin(request)
    except Exception as exc:
        raise HTTPException(
            403,
            {
                "code": "ORIGIN_FORBIDDEN",
                "message": "请求来源校验失败",
            },
        ) from exc


def _translate_setup_error(exc: SetupWorkflowError) -> HTTPException:
    return HTTPException(
        exc.status_code,
        {"code": exc.code, "message": exc.message},
    )


def _invalidate_alist_cache() -> None:
    from ...main import _alist_connection_cache

    _alist_connection_cache["data"] = None
    _alist_connection_cache["fetched_at"] = 0.0


@router.get("/api/admin/setup/status")
async def admin_setup_status():
    from ...main import StateSession

    async with StateSession() as session:
        setup_completed = await get_setup_completed(session)
    return {
        "setup_required": not setup_completed,
        "setup_available": bool(settings.setup_token),
    }


@router.post("/api/admin/setup/alist")
async def admin_setup_alist(
    payload: AListInput,
    request: Request,
):
    from ...main import StateSession

    _origin_or_403(request)
    async with StateSession() as session:
        setup_completed = await get_setup_completed(session)
        if setup_completed:
            raise HTTPException(
                409,
                {
                    "code": "SETUP_ALREADY_COMPLETED",
                    "message": "站点已完成初始化",
                },
            )
        if not settings.setup_token:
            raise HTTPException(
                503,
                {
                    "code": "SETUP_UNAVAILABLE",
                    "message": "服务器未配置初始化令牌",
                },
            )
        provided_token = request.headers.get(
            "X-CloudSite-Setup-Token",
            "",
        )
        if not verify_setup_token(
            provided_token,
            settings.setup_token,
        ):
            raise HTTPException(
                403,
                {
                    "code": "SETUP_FORBIDDEN",
                    "message": "初始化令牌错误",
                },
            )
        try:
            result = await complete_initial_alist_setup(
                session,
                base_url=payload.base_url,
                username=payload.username,
                password=payload.password,
                remember_credentials=payload.remember_credentials,
            )
        except SetupWorkflowError as exc:
            raise _translate_setup_error(exc) from exc

    _invalidate_alist_cache()
    return {
        "setup_completed": result["setup_completed"],
        "next": result["next"],
    }


class WizardStepData(BaseModel):
    model_config = {"extra": "allow"}

    base_url: str | None = None
    username: str | None = None
    password: str | None = None
    remember_credentials: bool | None = None
    root_mappings: list[dict[str, Any]] | None = None
    preset: Literal["software", "tutorial", "custom"] | None = None
    site_name: str | None = None
    home_title: str | None = None
    description: str | None = None
    hero_subtitle: str | None = None
    accent_color: str | None = None
    card_radius: int | None = None


class WizardStepInput(BaseModel):
    step: Literal[
        "connect",
        "scope",
        "preset",
        "samples",
        "brand",
        "preview",
        "publish",
    ]
    data: WizardStepData = Field(default_factory=WizardStepData)


@router.get("/api/admin/setup/wizard")
async def admin_setup_wizard_get():
    from ...main import StateSession

    async with StateSession() as session:
        return await get_wizard_state(session)


@router.post("/api/admin/setup/wizard/step")
async def admin_setup_wizard_step(
    payload: WizardStepInput,
    request: Request,
):
    from ...main import StateSession

    _origin_or_403(request)
    async with StateSession() as session:
        try:
            result = await process_wizard_step(
                session,
                step=payload.step,
                data=payload.data.model_dump(exclude_none=True),
                provided_setup_token=request.headers.get(
                    "X-CloudSite-Setup-Token",
                    "",
                ),
                expected_setup_token=settings.setup_token,
            )
        except SetupWorkflowError as exc:
            raise _translate_setup_error(exc) from exc

    if payload.step == "connect":
        _invalidate_alist_cache()
    return result


@router.post("/api/admin/setup/wizard/skip")
async def admin_setup_wizard_skip(request: Request):
    from ...main import StateSession

    _origin_or_403(request)
    async with StateSession() as session:
        try:
            return await skip_wizard(session)
        except SetupWorkflowError as exc:
            raise _translate_setup_error(exc) from exc
