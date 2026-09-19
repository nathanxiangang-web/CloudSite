"""First-run setup workflow orchestration.

Setup owns only wizard progress. Provider, presentation, site and system
settings are mutated through their existing boundaries instead of importing
their ORM models here.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....admin_auth import verify_setup_token
from ....platform.observability import write_operation_log
from ....platform.settings import (
    read_setup_completed,
    save_admin_system_settings,
)
from ...site.contracts.public import (
    get_admin_site_settings,
    update_admin_site_settings,
)
from ...presentation.contracts.public import (
    PresentationConfig,
    apply_admin_preset,
    get_admin_presentation,
    save_admin_presentation,
    toggle_admin_presentation,
)
from ...providers.contracts.public import (
    ProviderAdminError,
    save_setup_connection,
    update_root_mapping_preferences,
)
from ..infrastructure.models import SetupWizardState


WIZARD_STEPS: tuple[str, ...] = (
    "connect",
    "scope",
    "preset",
    "samples",
    "brand",
    "preview",
    "publish",
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


class SetupWorkflowError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _state_payload(row: SetupWizardState) -> dict[str, Any]:
    try:
        completed = json.loads(row.completed_steps_json or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
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


async def _get_or_create_wizard(
    state: AsyncSession,
) -> SetupWizardState:
    row = await state.get(SetupWizardState, 1)
    if row is None:
        row = SetupWizardState(
            id=1,
            current_step="connect",
            started_at=_now_iso(),
        )
        state.add(row)
        await state.flush()
    return row


def _advance_step(step: str) -> str:
    index = WIZARD_STEPS.index(step)
    return WIZARD_STEPS[
        min(index + 1, len(WIZARD_STEPS) - 1)
    ]


def _provider_error(exc: ProviderAdminError) -> SetupWorkflowError:
    return SetupWorkflowError(
        "ALIST_TEST_FAILED",
        f"AList 验证失败：{str(exc)[:200]}",
        status_code=400,
    )


async def get_wizard_state(
    state: AsyncSession,
) -> dict[str, Any]:
    row = await _get_or_create_wizard(state)
    await state.commit()
    return _state_payload(row)


async def get_setup_status(
    state: AsyncSession,
    *,
    setup_available: bool,
) -> dict[str, bool]:
    setup_completed = await read_setup_completed(state)
    return {
        "setup_required": not setup_completed,
        "setup_available": setup_available,
    }


async def complete_initial_alist_setup(
    state: AsyncSession,
    *,
    base_url: str,
    username: str,
    password: str,
    remember_credentials: bool,
    provided_setup_token: str,
    expected_setup_token: str,
) -> dict[str, Any]:
    if await read_setup_completed(state):
        raise SetupWorkflowError(
            "SETUP_ALREADY_COMPLETED",
            "站点已完成初始化",
            status_code=409,
        )
    if not expected_setup_token:
        raise SetupWorkflowError(
            "SETUP_UNAVAILABLE",
            "服务器未配置初始化令牌",
            status_code=503,
        )
    if not verify_setup_token(
        provided_setup_token,
        expected_setup_token,
    ):
        raise SetupWorkflowError(
            "SETUP_FORBIDDEN",
            "初始化令牌错误",
            status_code=403,
        )

    try:
        result = await save_setup_connection(
            state,
            base_url=base_url,
            username=username,
            password=password,
            remember_credentials=remember_credentials,
        )
    except ProviderAdminError as exc:
        raise _provider_error(exc) from exc

    await save_admin_system_settings(
        state,
        values={"setup_completed": True},
    )
    await write_operation_log(
        state,
        module="setup",
        action="alist_init",
        message="一次性初始化完成，AList 配置已保存",
    )
    await state.commit()
    return {
        "setup_completed": True,
        "next": "/admin/login",
        "base_path": result["base_path"],
    }


async def _process_connect(
    state: AsyncSession,
    row: SetupWizardState,
    data: dict[str, Any],
    *,
    provided_setup_token: str,
    expected_setup_token: str,
) -> dict[str, Any]:
    base_url = str(data.get("base_url") or "")
    username = str(data.get("username") or "")
    password = str(data.get("password") or "")
    if not base_url or not username:
        raise SetupWorkflowError(
            "WIZARD_CONNECT_MISSING",
            "请填写 AList 地址和用户名",
        )

    setup_completed = await read_setup_completed(state)
    if not setup_completed and not row.connect_done:
        if not expected_setup_token:
            raise SetupWorkflowError(
                "SETUP_UNAVAILABLE",
                "服务器未配置初始化令牌",
                status_code=503,
            )
        if not verify_setup_token(
            provided_setup_token,
            expected_setup_token,
        ):
            raise SetupWorkflowError(
                "SETUP_FORBIDDEN",
                "初始化令牌错误",
                status_code=403,
            )

    remember = data.get("remember_credentials")
    remember_credentials = (
        bool(remember) if remember is not None else True
    )
    try:
        result = await save_setup_connection(
            state,
            base_url=base_url,
            username=username,
            password=password,
            remember_credentials=remember_credentials,
        )
    except ProviderAdminError as exc:
        raise _provider_error(exc) from exc

    await write_operation_log(
        state,
        module="setup",
        action="wizard_connect",
        message="向导：AList 连接已保存",
    )
    return {"base_path": result["base_path"]}


async def _process_scope(
    state: AsyncSession,
    data: dict[str, Any],
) -> dict[str, Any]:
    mappings = data.get("root_mappings")
    if mappings is None:
        return {"updated": 0}
    updated = await update_root_mapping_preferences(
        state,
        updates=list(mappings),
    )
    await write_operation_log(
        state,
        module="setup",
        action="wizard_scope",
        message=f"向导：更新 {updated} 个根目录映射启用状态",
    )
    return {"updated": updated}


async def _process_preset(
    state: AsyncSession,
    data: dict[str, Any],
) -> dict[str, Any]:
    preset = data.get("preset")
    if preset is None:
        raise SetupWorkflowError(
            "WIZARD_PRESET_MISSING",
            "请选择预设",
        )

    preset_id = str(preset)
    if preset_id in {"software", "tutorial"}:
        result = await apply_admin_preset(
            state,
            preset_id=preset_id,
        )
        config = result["config"]
    else:
        config_model = PresentationConfig(preset="custom")
        result = await save_admin_presentation(
            state,
            cfg=config_model,
            summary="向导：应用 custom 预设",
        )
        config = result["config"]

    await toggle_admin_presentation(
        state,
        enabled=True,
    )
    await write_operation_log(
        state,
        module="setup",
        action="wizard_preset",
        message=f"向导：应用预设 {preset_id}",
    )
    return {"preset": str(config.get("preset") or preset_id)}


async def _process_samples(
    state: AsyncSession,
) -> dict[str, Any]:
    await write_operation_log(
        state,
        module="setup",
        action="wizard_samples",
        message="向导：样本整理已标记完成",
    )
    return {"marked": True}


async def _process_brand(
    state: AsyncSession,
    data: dict[str, Any],
) -> dict[str, Any]:
    site_values = {
        key: data[key]
        for key in (
            "site_name",
            "home_title",
            "description",
            "hero_subtitle",
        )
        if data.get(key) is not None
    }
    if site_values:
        site = await update_admin_site_settings(
            state,
            values=site_values,
        )
    else:
        site = await get_admin_site_settings(state)

    if (
        data.get("accent_color") is not None
        or data.get("card_radius") is not None
    ):
        presentation = await get_admin_presentation(state)
        config = presentation["config"]
        cfg = PresentationConfig(
            preset=config.get("preset", "custom"),
            theme_tokens=config.get("theme_tokens", {}),
            navigation=config.get("navigation", []),
            home_blocks=config.get("home_blocks", []),
        )
        theme = cfg.theme_tokens.model_copy()
        if data.get("accent_color") is not None:
            theme.accent_color = str(data["accent_color"])
        if data.get("card_radius") is not None:
            theme.card_radius = int(data["card_radius"])
        cfg = cfg.model_copy(update={"theme_tokens": theme})
        await save_admin_presentation(
            state,
            cfg=cfg,
            summary="向导：更新品牌主题",
        )

    await write_operation_log(
        state,
        module="setup",
        action="wizard_brand",
        message="向导：品牌信息已保存",
    )
    return {"site_name": site["site_name"]}


async def _process_preview(
    state: AsyncSession,
) -> dict[str, Any]:
    site = await get_admin_site_settings(state)
    presentation = await get_admin_presentation(state)
    await write_operation_log(
        state,
        module="setup",
        action="wizard_preview",
        message="向导：预览快照已生成",
    )
    return {
        "site_name": site["site_name"],
        "home_title": site["home_title"],
        "presentation_enabled": bool(
            presentation["enabled"]
        ),
        "preset": str(
            presentation["config"].get("preset") or "software"
        ),
    }


async def _process_publish(
    state: AsyncSession,
) -> dict[str, Any]:
    await save_admin_system_settings(
        state,
        values={"setup_completed": True},
    )
    await write_operation_log(
        state,
        module="setup",
        action="wizard_publish",
        message="向导：建站完成",
    )
    return {"setup_completed": True}


async def process_wizard_step(
    state: AsyncSession,
    *,
    step: str,
    data: dict[str, Any],
    provided_setup_token: str = "",
    expected_setup_token: str = "",
) -> dict[str, Any]:
    if step not in WIZARD_STEPS:
        raise SetupWorkflowError(
            "WIZARD_STEP_INVALID",
            "向导步骤无效",
        )

    row = await _get_or_create_wizard(state)
    if step == "connect":
        result = await _process_connect(
            state,
            row,
            data,
            provided_setup_token=provided_setup_token,
            expected_setup_token=expected_setup_token,
        )
    elif step == "scope":
        result = await _process_scope(state, data)
    elif step == "preset":
        result = await _process_preset(state, data)
    elif step == "samples":
        result = await _process_samples(state)
    elif step == "brand":
        result = await _process_brand(state, data)
    elif step == "preview":
        result = await _process_preview(state)
    else:
        result = await _process_publish(state)

    setattr(row, _STEP_DONE_FIELD[step], True)
    try:
        completed = set(
            json.loads(row.completed_steps_json or "[]")
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        completed = set()
    completed.add(step)
    row.completed_steps_json = json.dumps(
        sorted(
            completed,
            key=lambda item: WIZARD_STEPS.index(item),
        ),
        ensure_ascii=False,
    )
    if step == "publish":
        row.wizard_completed = True
        row.publish_done = True
        row.completed_at = _now_iso()
        row.current_step = "publish"
    else:
        row.current_step = _advance_step(step)

    state.add(row)
    await state.commit()
    return {
        "ok": True,
        "step": step,
        "result": result,
        "state": _state_payload(row),
    }


async def skip_wizard(
    state: AsyncSession,
) -> dict[str, Any]:
    row = await _get_or_create_wizard(state)
    row.wizard_completed = True
    row.current_step = "publish"
    row.completed_at = _now_iso()
    state.add(row)
    await save_admin_system_settings(
        state,
        values={"setup_completed": True},
    )
    await write_operation_log(
        state,
        module="setup",
        action="wizard_skip",
        message="向导已跳过，站点标记为完成初始化",
    )
    await state.commit()
    return {
        "ok": True,
        "state": _state_payload(row),
    }


__all__ = [
    "SetupWorkflowError",
    "WIZARD_STEPS",
    "complete_initial_alist_setup",
    "get_setup_status",
    "get_wizard_state",
    "process_wizard_step",
    "skip_wizard",
]
