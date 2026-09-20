"""Guarded browser-E2E support routes.

These routes are intentionally unavailable unless the deployment explicitly
opts into E2E seed mode and insecure-development mode.
"""

from fastapi import APIRouter, HTTPException, Request

from ..config import settings
from ..e2e_seed import seed_e2e_content

router = APIRouter()


def _e2e_seed_allowed(request: Request) -> bool:
    return bool(
        settings.e2e_seed_enabled
        and settings.allow_insecure_dev_key
        and request.headers.get("X-E2E-Run") == "1"
    )


@router.post("/api/_e2e/seed")
async def seed_browser_e2e(request: Request):
    if not _e2e_seed_allowed(request):
        raise HTTPException(status_code=404, detail="Not Found")

    from ..main import IndexSession, StateSession

    async with StateSession() as state, IndexSession() as index:
        return await seed_e2e_content(state, index)


__all__ = ["router"]
