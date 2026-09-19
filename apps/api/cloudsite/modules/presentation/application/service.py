"""Presentation lifecycle application service."""

from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....platform.observability import write_operation_log
from ..domain.config import (
    PRESETS,
    SOFTWARE_PRESET,
    PresentationConfig,
    config_dict,
    config_to_json,
    default_presentation,
    ordered_blocks,
    validate_config,
)
from ..infrastructure.models import (
    SitePresentation,
    SitePresentationRevision,
)


class PresentationError(RuntimeError):
    pass


class PresentationPresetUnknown(PresentationError):
    def __init__(self, preset: str):
        super().__init__(f"unknown presentation preset: {preset}")
        self.preset = preset


class PresentationRevisionNotFound(PresentationError):
    def __init__(self, revision_id: int):
        super().__init__(
            f"presentation revision not found: {revision_id}"
        )
        self.revision_id = revision_id


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


def _preset_summary(
    preset_id: str,
    cfg: PresentationConfig,
) -> dict:
    payload = config_dict(cfg)
    payload["preset"] = preset_id
    return payload


async def _save_revision(
    state: AsyncSession,
    current: SitePresentation,
    summary: str,
) -> None:
    state.add(
        SitePresentationRevision(
            revision=current.config_revision,
            preset=current.preset,
            theme_tokens_json=current.theme_tokens_json,
            navigation_json=current.navigation_json,
            home_blocks_json=current.home_blocks_json,
            summary=summary,
        )
    )


def _has_config(row: SitePresentation) -> bool:
    return bool(
        row.theme_tokens_json
        or row.navigation_json
        or row.home_blocks_json
    )


async def get_admin_presentation(
    state: AsyncSession,
) -> dict:
    row = await state.get(SitePresentation, 1)
    if row is not None:
        cfg = validate_config(
            row.preset,
            row.theme_tokens_json,
            row.navigation_json,
            row.home_blocks_json,
        )
        enabled = bool(row.enabled)
        config_revision = row.config_revision
    else:
        cfg = default_presentation()
        enabled = False
        config_revision = 1

    revisions = list(
        (
            await state.scalars(
                select(SitePresentationRevision)
                .order_by(
                    desc(SitePresentationRevision.revision_id)
                )
                .limit(20)
            )
        ).all()
    )
    return {
        "enabled": enabled,
        "config_revision": config_revision,
        "config": config_dict(cfg),
        "presets": {
            preset_id: _preset_summary(preset_id, preset)
            for preset_id, preset in PRESETS.items()
        },
        "revisions": [
            _revision_dict(revision)
            for revision in revisions
        ],
    }


async def save_admin_presentation(
    state: AsyncSession,
    *,
    cfg: PresentationConfig,
    summary: str = "",
) -> dict:
    theme_json, nav_json, blocks_json = config_to_json(cfg)
    row = (
        await state.get(SitePresentation, 1)
        or SitePresentation(id=1)
    )
    if row.config_revision is None:
        row.config_revision = 1
    if _has_config(row):
        await _save_revision(
            state,
            row,
            summary or "更新站点呈现配置",
        )
    row.preset = cfg.preset
    row.theme_tokens_json = theme_json
    row.navigation_json = nav_json
    row.home_blocks_json = blocks_json
    row.config_revision = (row.config_revision or 1) + 1
    state.add(row)
    await write_operation_log(
        state,
        module="presentation",
        action="presentation_saved",
        message=(
            "发布站点呈现配置 revision "
            f"{row.config_revision}"
        ),
    )
    await state.commit()
    return {
        "ok": True,
        "config_revision": row.config_revision,
        "config": config_dict(cfg),
    }


async def apply_admin_preset(
    state: AsyncSession,
    *,
    preset_id: str,
) -> dict:
    cfg = PRESETS.get(preset_id)
    if cfg is None:
        raise PresentationPresetUnknown(preset_id)
    theme_json, nav_json, blocks_json = config_to_json(cfg)
    row = (
        await state.get(SitePresentation, 1)
        or SitePresentation(id=1)
    )
    if row.config_revision is None:
        row.config_revision = 1
    if _has_config(row):
        await _save_revision(
            state,
            row,
            f"应用预设 {preset_id} 前回退快照",
        )
    row.preset = cfg.preset
    row.theme_tokens_json = theme_json
    row.navigation_json = nav_json
    row.home_blocks_json = blocks_json
    row.config_revision = (row.config_revision or 1) + 1
    state.add(row)
    await write_operation_log(
        state,
        module="presentation",
        action="preset_applied",
        message=f"应用预设：{preset_id}",
    )
    await state.commit()
    return {
        "ok": True,
        "config_revision": row.config_revision,
        "config": config_dict(cfg),
    }


async def rollback_admin_presentation(
    state: AsyncSession,
    *,
    revision_id: int,
) -> dict:
    snapshot = await state.get(
        SitePresentationRevision,
        revision_id,
    )
    if snapshot is None:
        raise PresentationRevisionNotFound(revision_id)

    current = (
        await state.get(SitePresentation, 1)
        or SitePresentation(id=1)
    )
    if current.config_revision is None:
        current.config_revision = 1
    if _has_config(current):
        await _save_revision(
            state,
            current,
            (
                "回退到 revision "
                f"{snapshot.revision} 前快照"
            ),
        )

    current.preset = snapshot.preset
    current.theme_tokens_json = snapshot.theme_tokens_json
    current.navigation_json = snapshot.navigation_json
    current.home_blocks_json = snapshot.home_blocks_json
    current.config_revision = (
        current.config_revision or 1
    ) + 1
    state.add(current)
    await write_operation_log(
        state,
        module="presentation",
        action="presentation_rolled_back",
        message=(
            "回退到历史配置 revision "
            f"{snapshot.revision}"
        ),
    )
    await state.commit()

    cfg = validate_config(
        current.preset,
        current.theme_tokens_json,
        current.navigation_json,
        current.home_blocks_json,
    )
    return {
        "ok": True,
        "config_revision": current.config_revision,
        "config": config_dict(cfg),
    }


async def toggle_admin_presentation(
    state: AsyncSession,
    *,
    enabled: bool,
) -> dict:
    row = (
        await state.get(SitePresentation, 1)
        or SitePresentation(id=1)
    )
    if not row.home_blocks_json or row.home_blocks_json == "[]":
        theme_json, nav_json, blocks_json = config_to_json(
            SOFTWARE_PRESET
        )
        row.preset = SOFTWARE_PRESET.preset
        row.theme_tokens_json = theme_json
        row.navigation_json = nav_json
        row.home_blocks_json = blocks_json
    row.enabled = enabled
    state.add(row)
    await write_operation_log(
        state,
        module="presentation",
        action="presentation_toggled",
        message=f"站点呈现{'启用' if enabled else '停用'}",
    )
    await state.commit()
    return {"ok": True, "enabled": enabled}


async def public_presentation(
    state: AsyncSession,
) -> dict:
    """Persistence-neutral presentation projection for public pages."""

    row = await state.get(SitePresentation, 1)
    if row is not None and row.enabled:
        cfg = validate_config(
            row.preset,
            row.theme_tokens_json,
            row.navigation_json,
            row.home_blocks_json,
        )
        enabled = True
    else:
        cfg = default_presentation()
        enabled = False
    return {
        "enabled": enabled,
        "preset": cfg.preset,
        "theme_tokens": cfg.theme_tokens.model_dump(),
        "navigation": [
            item.model_dump() for item in cfg.navigation
        ],
        "ordered_blocks": [
            block.model_dump()
            for block in ordered_blocks(cfg)
        ],
    }


__all__ = [
    "PresentationError",
    "PresentationPresetUnknown",
    "PresentationRevisionNotFound",
    "get_admin_presentation",
    "save_admin_presentation",
    "apply_admin_preset",
    "rollback_admin_presentation",
    "toggle_admin_presentation",
    "public_presentation",
]
