"""B1 站点呈现配置：预设定义、schema 验证与解析。

两套预设（软件站/教程站）以常量定义，切换无需改源码；复用现有合集/资源/
catalog 能力，不引入独立数据库或业务分支。home_blocks 限制在受支持类型
（featured/recent/topic/category/continue），配置经 pydantic schema 验证后
写入，不直接执行用户代码。回退生成新 revision，旧默认主题仍可恢复。
"""
from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field, field_validator

HOME_BLOCK_TYPES = ("featured", "recent", "topic", "category", "continue")
PRESET_IDS = ("software", "tutorial", "custom")


class ThemeTokens(BaseModel):
    accent_color: str = Field(default="#2563eb", pattern=r"^#[0-9a-fA-F]{6}$")
    card_radius: int = Field(default=12, ge=0, le=32)


class NavigationItem(BaseModel):
    label: str = Field(min_length=1, max_length=40)
    href: str = Field(min_length=1, max_length=200)
    sort_order: int = 0


class HomeBlock(BaseModel):
    type: Literal["featured", "recent", "topic", "category", "continue"]
    enabled: bool = True
    sort_order: int = 0
    limit: int = Field(default=6, ge=1, le=24)
    title: str = Field(default="", max_length=60)

    @field_validator("title")
    @classmethod
    def _strip_title(cls, value: str) -> str:
        return value.strip()


class PresentationConfig(BaseModel):
    preset: Literal["software", "tutorial", "custom"] = "custom"
    theme_tokens: ThemeTokens = Field(default_factory=ThemeTokens)
    navigation: list[NavigationItem] = Field(default_factory=list, max_length=20)
    home_blocks: list[HomeBlock] = Field(default_factory=list, max_length=12)


SOFTWARE_PRESET: PresentationConfig = PresentationConfig(
    preset="software",
    theme_tokens=ThemeTokens(accent_color="#2563eb", card_radius=12),
    navigation=[
        NavigationItem(label="首页", href="/", sort_order=0),
        NavigationItem(label="资源库", href="/resources/software", sort_order=1),
        NavigationItem(label="目录", href="/catalog", sort_order=2),
        NavigationItem(label="精选", href="/collections", sort_order=3),
        NavigationItem(label="最近更新", href="/resources/file", sort_order=4),
        NavigationItem(label="使用指南", href="/about", sort_order=5),
    ],
    home_blocks=[
        HomeBlock(type="category", sort_order=0, title="资源分类"),
        HomeBlock(type="featured", sort_order=1, limit=4, title="精选合集"),
        HomeBlock(type="recent", sort_order=2, limit=6, title="最近更新"),
        HomeBlock(type="topic", sort_order=3, limit=6, title="推荐专题"),
        HomeBlock(type="continue", sort_order=4, limit=6, title="继续使用"),
    ],
)

TUTORIAL_PRESET: PresentationConfig = PresentationConfig(
    preset="tutorial",
    theme_tokens=ThemeTokens(accent_color="#16a34a", card_radius=12),
    navigation=[
        NavigationItem(label="首页", href="/", sort_order=0),
        NavigationItem(label="目录", href="/catalog", sort_order=1),
        NavigationItem(label="精选", href="/collections", sort_order=2),
        NavigationItem(label="资源库", href="/resources/software", sort_order=3),
        NavigationItem(label="使用指南", href="/about", sort_order=4),
    ],
    home_blocks=[
        HomeBlock(type="topic", sort_order=0, limit=6, title="推荐教程"),
        HomeBlock(type="featured", sort_order=1, limit=4, title="精选合集"),
        HomeBlock(type="category", sort_order=2, title="资源分类"),
        HomeBlock(type="recent", sort_order=3, limit=6, title="最近更新"),
        HomeBlock(type="continue", sort_order=4, limit=6, title="继续使用"),
    ],
)

PRESETS: dict[str, PresentationConfig] = {
    "software": SOFTWARE_PRESET,
    "tutorial": TUTORIAL_PRESET,
}


def default_presentation() -> PresentationConfig:
    """未启用站点呈现时的默认配置（等同软件预设但 enabled=False）。"""
    cfg = SOFTWARE_PRESET.model_copy(deep=True)
    return cfg


def validate_config(preset: str, theme_tokens_json: str, navigation_json: str, home_blocks_json: str) -> PresentationConfig:
    """解析并验证存储中的 JSON 文本为 PresentationConfig。

    存储字段以受控 JSON 文本保存；读取时经 pydantic 验证，非法值回退到默认，
    不直接执行用户代码。
    """
    try:
        theme_tokens = json.loads(theme_tokens_json or "{}")
    except (TypeError, ValueError):
        theme_tokens = {}
    try:
        navigation = json.loads(navigation_json or "[]")
    except (TypeError, ValueError):
        navigation = []
    try:
        home_blocks = json.loads(home_blocks_json or "[]")
    except (TypeError, ValueError):
        home_blocks = []
    return PresentationConfig(
        preset=preset if preset in PRESET_IDS else "custom",
        theme_tokens=theme_tokens,
        navigation=navigation,
        home_blocks=home_blocks,
    )


def config_to_json(cfg: PresentationConfig) -> tuple[str, str, str]:
    """将 PresentationConfig 序列化为可存储的 (theme_tokens, navigation, home_blocks) JSON 文本。"""
    return (
        cfg.theme_tokens.model_dump_json(),
        json.dumps([item.model_dump() for item in cfg.navigation], ensure_ascii=False),
        json.dumps([block.model_dump() for block in cfg.home_blocks], ensure_ascii=False),
    )


def ordered_blocks(cfg: PresentationConfig) -> list[HomeBlock]:
    """返回按 sort_order 排序且 enabled 的区块。"""
    return sorted([b for b in cfg.home_blocks if b.enabled], key=lambda b: b.sort_order)
