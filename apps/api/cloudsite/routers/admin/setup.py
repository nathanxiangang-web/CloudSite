"""admin/setup 路由：站点一次性初始化。"""
from fastapi import APIRouter, HTTPException, Request

from ...admin_auth import get_setup_completed, verify_setup_token
from ...alist import AListClient
from ...config import settings
from ...crypto import encrypt_secret
from ...models import AListConnection, OperationLog, SystemSetting, utcnow
from ...auth import validate_request_origin
from ...schemas import AListInput

router = APIRouter()


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
async def admin_setup_alist(payload: AListInput, request: Request):
    from ...main import StateSession, _alist_connection_cache

    # M3: 一次性初始化，固定处理顺序
    # 1. 同源校验（中间件已对公开写端点执行，这里二次确认）
    try:
        validate_request_origin(request)
    except Exception:
        raise HTTPException(403, {"code": "ORIGIN_FORBIDDEN", "message": "请求来源校验失败"})
    # 2. 检查是否仍为 setup_required
    async with StateSession() as session:
        setup_completed = await get_setup_completed(session)
        if setup_completed:
            raise HTTPException(409, {"code": "SETUP_ALREADY_COMPLETED", "message": "站点已完成初始化"})
        # 3. 检查初始化令牌
        if not settings.setup_token:
            raise HTTPException(503, {"code": "SETUP_UNAVAILABLE", "message": "服务器未配置初始化令牌"})
        provided_token = request.headers.get("X-CloudSite-Setup-Token", "")
        if not verify_setup_token(provided_token, settings.setup_token):
            raise HTTPException(403, {"code": "SETUP_FORBIDDEN", "message": "初始化令牌错误"})
        # 4. 校验请求字段（AListInput 已由 Pydantic 完成）
        # 5. 使用提交的配置测试 AList 登录
        try:
            result = await AListClient(payload.base_url, payload.username, payload.password).test()
        except Exception as exc:
            raise HTTPException(400, {"code": "ALIST_TEST_FAILED", "message": f"AList 验证失败：{str(exc)[:200]}"}) from exc
        # 6. 测试成功后保存 AList 配置 + 写入 setup_completed（同一事务）
        row = await session.get(AListConnection, 1) or AListConnection(id=1)
        row.base_url = payload.base_url.rstrip("/")
        row.base_path = result.get("base_path") or "/"
        row.username = payload.username
        row.password_ciphertext = encrypt_secret(payload.password) if payload.remember_credentials else ""
        row.remember_credentials = payload.remember_credentials
        row.enabled = True
        row.last_test_status = "success"
        row.last_test_message = "初始化时 AList 连接验证成功"
        row.last_test_at = utcnow()
        session.add(row)
        session.add(SystemSetting(key="setup_completed", value="true", value_type="string"))
        session.add(OperationLog(module="setup", action="alist_init", message="一次性初始化完成，AList 配置已保存"))
        await session.commit()
    # 7. 清理 AList 配置缓存
    _alist_connection_cache["data"] = None
    _alist_connection_cache["fetched_at"] = 0.0
    return {"setup_completed": True, "next": "/admin/login"}

# ---- B2 首次建站向导 ----

import json
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select

from ...models import ContentRootMapping, SetupWizardState, SiteSettings, SitePresentation
from ...services.presentation import PRESETS, PresentationConfig, config_to_json

WIZARD_STEPS: tuple[str, ...] = (
    "connect", "scope", "preset", "samples", "brand", "preview", "publish",
)
_STEP_DONE_FIELD = {
    "connect": "connect_done",
    "scope": "scope_done",
    "preset": "preset_done",
    "samples": "samples_done",
    "brand": "brand_done",
    "preview": "preview_done",
    "publish": "publish_done",
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
    step: Literal["connect", "scope", "preset", "samples", "brand", "preview", "publish"]
    data: WizardStepData = Field(default_factory=WizardStepData)


def _wizard_state_dict(row: SetupWizardState) -> dict:
    try:
        completed = json.loads(row.completed_steps_json or "[]")
    except (TypeError, ValueError):
        completed = []
    return {
        "current_step": row.current_step,
        "completed_steps": completed,
        "connect_done": bool(row.connect_done),
        "scope_done": bool(row.scope_done),
        "preset_done": bool(row.preset_done),
        "samples_done": bool(row.samples_done),
        "brand_done": bool(row.brand_done),
        "preview_done": bool(row.preview_done),
        "publish_done": bool(row.publish_done),
        "wizard_completed": bool(row.wizard_completed),
        "started_at": row.started_at,
        "completed_at": row.completed_at,
    }


async def _get_or_create_wizard(session) -> SetupWizardState:
    row = await session.get(SetupWizardState, 1)
    if row is None:
        row = SetupWizardState(id=1, current_step="connect", started_at=utcnow().isoformat())
        session.add(row)
        await session.flush()
    return row


def _advance_step(step: str) -> str:
    idx = WIZARD_STEPS.index(step)
    return WIZARD_STEPS[min(idx + 1, len(WIZARD_STEPS) - 1)]


async def _process_connect(session, data: WizardStepData, request: Request, *, connect_already_done: bool = False) -> dict:
    """保存 AList 连接（复用现有验证逻辑），但不标记 setup_completed。

    首次连接需初始化令牌；回退重连时已认证过，无需再次校验令牌。
    """
    if not data.base_url or not data.username:
        raise HTTPException(400, {"code": "WIZARD_CONNECT_MISSING", "message": "请填写 AList 地址和用户名"})
    setup_completed = await get_setup_completed(session)
    if not setup_completed and not connect_already_done:
        if not settings.setup_token:
            raise HTTPException(503, {"code": "SETUP_UNAVAILABLE", "message": "服务器未配置初始化令牌"})
        provided_token = request.headers.get("X-CloudSite-Setup-Token", "")
        if not verify_setup_token(provided_token, settings.setup_token):
            raise HTTPException(403, {"code": "SETUP_FORBIDDEN", "message": "初始化令牌错误"})
    try:
        result = await AListClient(data.base_url, data.username, data.password or "").test()
    except Exception as exc:
        raise HTTPException(400, {"code": "ALIST_TEST_FAILED", "message": f"AList 验证失败：{str(exc)[:200]}"}) from exc
    row = await session.get(AListConnection, 1) or AListConnection(id=1)
    row.base_url = data.base_url.rstrip("/")
    row.base_path = result.get("base_path") or "/"
    row.username = data.username
    remember = data.remember_credentials if data.remember_credentials is not None else True
    row.password_ciphertext = encrypt_secret(data.password or "") if remember else ""
    row.remember_credentials = remember
    row.enabled = True
    row.last_test_status = "success"
    row.last_test_message = "向导连接步骤验证成功"
    row.last_test_at = utcnow()
    session.add(row)
    session.add(OperationLog(module="setup", action="wizard_connect", message="向导：AList 连接已保存"))
    return {"base_path": row.base_path}


async def _process_scope(session, data: WizardStepData) -> dict:
    """选择启用哪些 ContentRootMapping。"""
    if data.root_mappings is None:
        return {"updated": 0}
    updated = 0
    for item in data.root_mappings:
        mapping_id = item.get("id")
        if mapping_id is None:
            continue
        row = await session.get(ContentRootMapping, int(mapping_id))
        if row is None:
            continue
        if "enabled" in item:
            row.enabled = bool(item["enabled"])
            updated += 1
        if "sort_order" in item:
            row.sort_order = int(item["sort_order"])
    session.add(OperationLog(module="setup", action="wizard_scope", message=f"向导：更新 {updated} 个根目录映射启用状态"))
    return {"updated": updated}


async def _process_preset(session, data: WizardStepData) -> dict:
    """选择预设并写入 SitePresentation。"""
    if data.preset is None:
        raise HTTPException(400, {"code": "WIZARD_PRESET_MISSING", "message": "请选择预设"})
    if data.preset in PRESETS:
        cfg = PRESETS[data.preset]
    else:
        cfg = PresentationConfig(preset="custom")
    theme_json, nav_json, blocks_json = config_to_json(cfg)
    row = await session.get(SitePresentation, 1) or SitePresentation(id=1)
    row.preset = cfg.preset
    row.theme_tokens_json = theme_json
    row.navigation_json = nav_json
    row.home_blocks_json = blocks_json
    row.enabled = True
    row.config_revision = (row.config_revision or 1) + 1
    session.add(row)
    session.add(OperationLog(module="setup", action="wizard_preset", message=f"向导：应用预设 {data.preset}"))
    return {"preset": cfg.preset}


async def _process_samples(session, data: WizardStepData) -> dict:
    """标记样本整理完成（不做实际整理，仅记录）。"""
    session.add(OperationLog(module="setup", action="wizard_samples", message="向导：样本整理已标记完成"))
    return {"marked": True}


async def _process_brand(session, data: WizardStepData) -> dict:
    """保存站点名称、品牌信息（更新 SiteSettings + SitePresentation 主题色）。"""
    settings_row = await session.get(SiteSettings, 1) or SiteSettings(id=1)
    if data.site_name is not None:
        settings_row.site_name = data.site_name
    if data.home_title is not None:
        settings_row.home_title = data.home_title
    if data.description is not None:
        settings_row.description = data.description
    if data.hero_subtitle is not None:
        settings_row.hero_subtitle = data.hero_subtitle
    session.add(settings_row)
    if data.accent_color is not None or data.card_radius is not None:
        from ...services.presentation import validate_config
        pres_row = await session.get(SitePresentation, 1)
        if pres_row is not None:
            cfg = validate_config(pres_row.preset, pres_row.theme_tokens_json, pres_row.navigation_json, pres_row.home_blocks_json)
            theme = cfg.theme_tokens.model_copy()
            if data.accent_color is not None:
                theme.accent_color = data.accent_color
            if data.card_radius is not None:
                theme.card_radius = data.card_radius
            cfg = cfg.model_copy(update={"theme_tokens": theme})
            theme_json, nav_json, blocks_json = config_to_json(cfg)
            pres_row.theme_tokens_json = theme_json
            pres_row.navigation_json = nav_json
            pres_row.home_blocks_json = blocks_json
            session.add(pres_row)
    session.add(OperationLog(module="setup", action="wizard_brand", message="向导：品牌信息已保存"))
    return {"site_name": settings_row.site_name}


async def _process_preview(session, data: WizardStepData) -> dict:
    """生成预览快照（不发布，仅记录）。"""
    settings_row = await session.get(SiteSettings, 1) or SiteSettings(id=1)
    pres_row = await session.get(SitePresentation, 1)
    preview = {
        "site_name": settings_row.site_name,
        "home_title": settings_row.home_title,
        "presentation_enabled": bool(pres_row.enabled) if pres_row else False,
        "preset": pres_row.preset if pres_row else "software",
    }
    session.add(OperationLog(module="setup", action="wizard_preview", message="向导：预览快照已生成"))
    return preview


async def _process_publish(session, data: WizardStepData) -> dict:
    """标记向导完成并设置 setup_completed。"""
    session.add(SystemSetting(key="setup_completed", value="true", value_type="string"))
    session.add(OperationLog(module="setup", action="wizard_publish", message="向导：建站完成"))
    return {"setup_completed": True}


_STEP_PROCESSORS = {
    "connect": _process_connect,
    "scope": _process_scope,
    "preset": _process_preset,
    "samples": _process_samples,
    "brand": _process_brand,
    "preview": _process_preview,
    "publish": _process_publish,
}


@router.get("/api/admin/setup/wizard")
async def admin_setup_wizard_get():
    from ...main import StateSession

    async with StateSession() as session:
        row = await _get_or_create_wizard(session)
        await session.commit()
        return _wizard_state_dict(row)


@router.post("/api/admin/setup/wizard/step")
async def admin_setup_wizard_step(payload: WizardStepInput, request: Request):
    from ...main import StateSession, _alist_connection_cache

    try:
        validate_request_origin(request)
    except Exception:
        raise HTTPException(403, {"code": "ORIGIN_FORBIDDEN", "message": "请求来源校验失败"})
    step = payload.step
    processor = _STEP_PROCESSORS[step]
    async with StateSession() as session:
        row = await _get_or_create_wizard(session)
        if step == "connect":
            result = await processor(session, payload.data, request, connect_already_done=bool(row.connect_done))
        else:
            result = await processor(session, payload.data)
        setattr(row, _STEP_DONE_FIELD[step], True)
        completed = set(json.loads(row.completed_steps_json or "[]"))
        completed.add(step)
        row.completed_steps_json = json.dumps(sorted(completed, key=lambda s: WIZARD_STEPS.index(s)), ensure_ascii=False)
        if step == "publish":
            row.wizard_completed = True
            row.publish_done = True
            row.completed_at = utcnow().isoformat()
            row.current_step = "publish"
        else:
            row.current_step = _advance_step(step)
        session.add(row)
        await session.commit()
        if step == "connect":
            _alist_connection_cache["data"] = None
            _alist_connection_cache["fetched_at"] = 0.0
        state = _wizard_state_dict(row)
    return {"ok": True, "step": step, "result": result, "state": state}


@router.post("/api/admin/setup/wizard/skip")
async def admin_setup_wizard_skip(request: Request):
    from ...main import StateSession

    try:
        validate_request_origin(request)
    except Exception:
        raise HTTPException(403, {"code": "ORIGIN_FORBIDDEN", "message": "请求来源校验失败"})
    async with StateSession() as session:
        row = await _get_or_create_wizard(session)
        row.wizard_completed = True
        row.current_step = "publish"
        row.completed_at = utcnow().isoformat()
        session.add(SystemSetting(key="setup_completed", value="true", value_type="string"))
        session.add(OperationLog(module="setup", action="wizard_skip", message="向导已跳过，站点标记为完成初始化"))
        session.add(row)
        await session.commit()
        return {"ok": True, "state": _wizard_state_dict(row)}
