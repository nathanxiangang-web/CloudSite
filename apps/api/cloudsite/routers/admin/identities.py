"""admin/identities route: authentication + HTTP boundary only."""

from fastapi import APIRouter, HTTPException, Query, Request

from ...infrastructure.security import verify_session_token
from ...modules.identity.api.admin_queries import (
    identity_candidates_payload,
    identity_stats_payload,
)

router = APIRouter()

SESSION_COOKIE = "cloudsite_session"


def require_explicit_admin(request: Request) -> None:
    if not verify_session_token(request.cookies.get(SESSION_COOKIE)):
        raise HTTPException(
            status_code=403,
            detail={"code": "ADMIN_REQUIRED", "message": "请先登录管理后台"},
        )


@router.get("/api/admin/identities/stats")
async def identity_stats(request: Request):
    require_explicit_admin(request)
    return await identity_stats_payload()


@router.get("/api/admin/identities/candidates")
async def identity_candidates(
    request: Request,
    status: str = Query(
        "open",
        pattern="^(open|pending|ambiguous|resolved_move|resolved_new|cancelled)$",
    ),
    limit: int = Query(50, ge=1, le=200),
):
    require_explicit_admin(request)
    return await identity_candidates_payload(status=status, limit=limit)
