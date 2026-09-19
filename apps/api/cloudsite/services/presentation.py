"""Compatibility facade for Presentation configuration primitives.

New code must import from
`cloudsite.modules.presentation.contracts.public`.
"""

from ..modules.presentation.contracts.public import (
    HOME_BLOCK_TYPES,
    PRESET_IDS,
    PRESETS,
    SOFTWARE_PRESET,
    TUTORIAL_PRESET,
    HomeBlock,
    NavigationItem,
    PresentationConfig,
    ThemeTokens,
    config_dict,
    config_to_json,
    default_presentation,
    ordered_blocks,
    validate_config,
)

__all__ = [
    "HOME_BLOCK_TYPES",
    "PRESET_IDS",
    "PRESETS",
    "SOFTWARE_PRESET",
    "TUTORIAL_PRESET",
    "ThemeTokens",
    "NavigationItem",
    "HomeBlock",
    "PresentationConfig",
    "config_dict",
    "config_to_json",
    "default_presentation",
    "ordered_blocks",
    "validate_config",
]
