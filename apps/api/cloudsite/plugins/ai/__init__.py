"""AI plugin — AI completion + cloud download features.

Enabled by default.  Set ENABLE_AI_PLUGIN=false to disable.
"""
from __future__ import annotations

from fastapi import APIRouter

from cloudsite.plugins.ai.routes.ai_completion import router as ai_completion_router
from cloudsite.plugins.ai.routes.cloud_download import router as cloud_download_router


class AIPlugin:
    """Pluggable AI features: content completion and cloud download."""

    name = "ai"
    version = "1.0.0"

    def get_routers(self) -> list[APIRouter]:
        return [ai_completion_router, cloud_download_router]


plugin = AIPlugin()
