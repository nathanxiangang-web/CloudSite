"""admin/presentation 路由：B1 站点呈现配置管理。

支持启停、预设切换、区块排序、预览、发布与回退。每次发布写一条历史快照
（SitePresentationRevision），回退生成新 revision 而非覆盖历史；旧默认
主题仍可恢复（enabled=False 回退到默认区块顺序）。配置经 pydantic schema
验证，不直接执行用户代码。复用现有合集/资源/catalog 能力，不引入独立
数据库或业务分支。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from typing import Literal

from ...auth import validate_request_origin
from ...models import OperationLog, SitePresentation, SitePresentationRevision
from ...services.presentation import (
    PRESETS,
    PresentationConfig,
    config_to_json,
    default_presentation,
    ordered_blocks,
    validate_config,
)
from ..home import invalidate_home_cache

router = APIRouter()


class ThemeTokensInput(BaseModel):
    accent_color: str = Field(default="#2563eb", pattern=r"^#[0-9a-fA-F]{6}$")
    card_radius: int = Field(default=12, ge=0, le=32)


class NavigationItemInput(BaseModel):
    label: str = Field(min_length=1, max_length=40)
    href: str = Field(min_length=1, max_length=200)
    sort_order: int = 0


class HomeBlockInput(BaseModel):
    type: Literal["featured", "recent", "topic", "category", "continue"]
    enabled: bool = True
    sort_order: int = 0
    limit: int = Field(default=6, ge=1, le=24)
    title: str = Field(default="", max_length=60)


class PresentationUpdate(BaseModel):
    preset: Literal["software", "tutorial", "custom"] = "custom"
    theme_tokens: ThemeTokensInput = Field(default_factory=ThemeTokensInput)
    navigation: list[NavigationItemInput] = Field(default_factory=list, max_length=20)
    home_blocks: list[HomeBlockInput] = Field(default_factory=list, max_length=12)
    summary: str = Field(default="", max_length=200)


class ApplyPresetInput(BaseModel):
    preset: Literal["software", "tutorial"]


class RollbackInput(BaseModel):
    revision_id: int


class ToggleInput(BaseModel):
    enabled: bool


def _config_dict(cfg: PresentationConfig) -> dict:
    return {
        "preset": cfg.preset,
        "theme_tokens": cfg.theme_tokens.model_dump(),
        "navigation": [item.model_dump() for item in cfg.navigation],
        "home_blocks": [block.model_dump() for block in cfg.home_blocks],
        "ordered_blocks": [block.model_dump() for block in ordered_blocks(cfg)],
    }


def _revision_dict(row: SitePresentationRevision) -> dict:
    return {
        "revision_id": row.revision_id,
        "revision": row.revision,
        "preset": row.preset,
        "theme_tokens_json": row.theme_tokens_json,
        "navigation_json": row.navigation_json,
        "home_blocks_json": row.home_blocks_json,
        "summary": row.summary,
        "created_by": row.created_by,
        "created_at": row.created_at,
    }


def _preset_summary(preset_id: str, cfg: PresentationConfig) -> dict:
    return {
        "preset": preset_id,
        "theme_tokens": cfg.theme_tokens.model_dump(),
        "navigation": [item.model_dump() for item in cfg.navigation],
        "home_blocks": [block.model_dump() for block in cfg.home_blocks],
        "ordered_blocks": [block.model_dump() for block in ordered_blocks(cfg)],
    }


async def _save_revision(session, current: SitePresentation, summary: str) -> None:
    """将当前生效配置写入历史快照，用于回退。"""
    rev = SitePresentationRevision(
        revision=current.config_revision,
        preset=current.preset,
        theme_tokens_json=current.theme_tokens_json,
        navigation_json=current.navigation_json,
        home_blocks_json=current.home_blocks_json,
        summary=summary,
    )
    session.add(rev)


@router.get("/api/admin/presentation")
async def get_presentation():
    from ...main import StateSession

    async with StateSession() as session:
        row = await session.get(SitePresentation, 1)
        if row:
            cfg = validate_config(row.preset, row.theme_tokens_json, row.navigation_json, row.home_blocks_json)
            enabled = bool(row.enabled)
            config_revision = row.config_revision
        else:
            cfg = default_presentation()
            enabled = False
            config_revision = 1
        revisions = list((await session.scalars(select(SitePresentationRevision).order_by(desc(SitePresentationRevision.revision_id)).limit(20))).all())
        return {
            "enabled": enabled,
            "config_revision": config_revision,
            "config": _config_dict(cfg),
            "presets": {pid: _preset_summary(pid, pcfg) for pid, pcfg in PRESETS.items()},
            "revisions": [_revision_dict(r) for r in revisions],
        }


@router.put("/api/admin/presentation")
async def save_presentation(payload: PresentationUpdate, request: Request):
    from ...main import StateSession

    validate_request_origin(request)
    cfg = PresentationConfig(
        preset=payload.preset,
        theme_tokens=payload.theme_tokens.model_dump(),
        navigation=[item.model_dump() for item in payload.navigation],
        home_blocks=[block.model_dump() for block in payload.home_blocks],
    )
    theme_json, nav_json, blocks_json = config_to_json(cfg)
    async with StateSession() as session:
        row = await session.get(SitePresentation, 1) or SitePresentation(id=1)
        if row.config_revision is None:
            row.config_revision = 1
        # 保留上一配置可回退：先存历史快照
        if row.theme_tokens_json or row.navigation_json or row.home_blocks_json:
            await _save_revision(session, row, payload.summary or "更新站点呈现配置")
        row.preset = cfg.preset
        row.theme_tokens_json = theme_json
        row.navigation_json = nav_json
        row.home_blocks_json = blocks_json
        row.config_revision = (row.config_revision or 1) + 1
        session.add(row)
        session.add(OperationLog(level="INFO", module="presentation", action="presentation_saved", message=f"发布站点呈现配置 revision {row.config_revision}"))
        await session.commit()
        invalidate_home_cache()
        return {"ok": True, "config_revision": row.config_revision, "config": _config_dict(cfg)}


@router.post("/api/admin/presentation/apply-preset")
async def apply_preset(payload: ApplyPresetInput, request: Request):
    from ...main import StateSession

    validate_request_origin(request)
    cfg = PRESETS.get(payload.preset)
    if cfg is None:
        raise HTTPException(400, {"code": "PRESET_UNKNOWN", "message": f"未知预设：{payload.preset}"})
    theme_json, nav_json, blocks_json = config_to_json(cfg)
    async with StateSession() as session:
        row = await session.get(SitePresentation, 1) or SitePresentation(id=1)
        if row.config_revision is None:
            row.config_revision = 1
        if row.theme_tokens_json or row.navigation_json or row.home_blocks_json:
            await _save_revision(session, row, f"应用预设 {payload.preset} 前回退快照")
        row.preset = cfg.preset
        row.theme_tokens_json = theme_json
        row.navigation_json = nav_json
        row.home_blocks_json = blocks_json
        row.config_revision = (row.config_revision or 1) + 1
        session.add(row)
        session.add(OperationLog(level="INFO", module="presentation", action="preset_applied", message=f"应用预设：{payload.preset}"))
        await session.commit()
        invalidate_home_cache()
        return {"ok": True, "config_revision": row.config_revision, "config": _config_dict(cfg)}


@router.post("/api/admin/presentation/rollback")
async def rollback_presentation(payload: RollbackInput, request: Request):
    from ...main import StateSession

    validate_request_origin(request)
    async with StateSession() as session:
        snapshot = await session.get(SitePresentationRevision, payload.revision_id)
        if snapshot is None:
            raise HTTPException(404, {"code": "REVISION_NOT_FOUND", "message": "历史配置不存在"})
        current = await session.get(SitePresentation, 1) or SitePresentation(id=1)
        if current.config_revision is None:
            current.config_revision = 1
        # 回退前保留当前配置为新快照，回退生成新 revision 而非覆盖历史
        if current.theme_tokens_json or current.navigation_json or current.home_blocks_json:
            await _save_revision(session, current, f"回退到 revision {snapshot.revision} 前快照")
        current.preset = snapshot.preset
        current.theme_tokens_json = snapshot.theme_tokens_json
        current.navigation_json = snapshot.navigation_json
        current.home_blocks_json = snapshot.home_blocks_json
        current.config_revision = (current.config_revision or 1) + 1
        session.add(current)
        session.add(OperationLog(level="INFO", module="presentation", action="presentation_rolled_back", message=f"回退到历史配置 revision {snapshot.revision}"))
        await session.commit()
        invalidate_home_cache()
        cfg = validate_config(current.preset, current.theme_tokens_json, current.navigation_json, current.home_blocks_json)
        return {"ok": True, "config_revision": current.config_revision, "config": _config_dict(cfg)}


@router.put("/api/admin/presentation/toggle")
async def toggle_presentation(payload: ToggleInput, request: Request):
    from ...main import StateSession

    validate_request_origin(request)
    async with StateSession() as session:
        row = await session.get(SitePresentation, 1) or SitePresentation(id=1)
        if not row.home_blocks_json or row.home_blocks_json == "[]":
            # 首次启用且未配置：落入软件预设默认，无需改源码
            from ...services.presentation import SOFTWARE_PRESET
            theme_json, nav_json, blocks_json = config_to_json(SOFTWARE_PRESET)
            row.preset = SOFTWARE_PRESET.preset
            row.theme_tokens_json = theme_json
            row.navigation_json = nav_json
            row.home_blocks_json = blocks_json
        row.enabled = payload.enabled
        session.add(row)
        session.add(OperationLog(level="INFO", module="presentation", action="presentation_toggled", message=f"站点呈现{'启用' if payload.enabled else '停用'}"))
        await session.commit()
        invalidate_home_cache()
        return {"ok": True, "enabled": payload.enabled}
