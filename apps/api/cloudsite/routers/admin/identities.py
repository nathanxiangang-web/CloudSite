"""admin/identities route: authentication + HTTP parameters only."""

from fastapi import APIRouter, HTTPException, Query, Request

from ...infrastructure.security import verify_session_token
from ...modules.identity.composition import build_identity_admin_query_service

router = APIRouter()

SESSION_COOKIE = "cloudsite_session"
_queries = build_identity_admin_query_service()


def require_explicit_admin(request: Request) -> None:
    if not verify_session_token(request.cookies.get(SESSION_COOKIE)):
        raise HTTPException(
            status_code=403,
            detail={"code": "ADMIN_REQUIRED", "message": "请先登录管理后台"},
        )


@router.get("/api/admin/identities/stats")
async def identity_stats(request: Request):
    require_explicit_admin(request)
    return await _queries.stats()


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
    return await _queries.candidates(status=status, limit=limit)
