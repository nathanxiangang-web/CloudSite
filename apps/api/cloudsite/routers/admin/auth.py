"""admin/auth 路由：后台认证状态、登录、登出。"""
from fastapi import APIRouter, HTTPException, Request, Response

from ...admin_auth import AdminAuthMode, get_setup_completed
from ...alist import AListClient
from ...config import settings
from ...infrastructure.security import (
    ADMIN_SESSION_MAX_AGE_SECONDS,
    create_session_token,
    verify_session_token,
)
from ...models import AListConnection
from ...request_context import request_is_https
from ...schemas import AdminLoginInput

router = APIRouter()

SESSION_COOKIE = "cloudsite_session"


@router.get("/api/admin/auth/status")
async def admin_auth_status(request: Request):
    from ...main import StateSession

    async with StateSession() as session:
        setup_completed = await get_setup_completed(session)
    admin_cookie_valid = verify_session_token(request.cookies.get(SESSION_COOKIE))
    if not setup_completed:
        mode = AdminAuthMode.SETUP_REQUIRED
    elif not admin_cookie_valid:
        mode = AdminAuthMode.LOGIN_REQUIRED
    else:
        mode = AdminAuthMode.AUTHENTICATED
    return {
        "mode": mode,
        "authenticated": mode == AdminAuthMode.AUTHENTICATED,
        "auth_required": True,
    }


@router.post("/api/admin/auth/login")
async def admin_login(payload: AdminLoginInput, request: Request, response: Response):
    from ...main import StateSession

    async with StateSession() as session:
        setup_completed = await get_setup_completed(session)
        connection = await session.get(AListConnection, 1)
    if not setup_completed:
        raise HTTPException(409, {"code": "SETUP_REQUIRED", "message": "站点尚未完成初始化"})
    if not connection:
        raise HTTPException(409, {"code": "SETUP_REQUIRED", "message": "尚未配置 AList，请先完成初始化"})
    try:
        await AListClient(connection.base_url, payload.username, payload.password).test()
    except Exception as exc:
        raise HTTPException(401, "账号或密码错误") from exc
    response.set_cookie(
        SESSION_COOKIE,
        create_session_token(payload.username),
        max_age=ADMIN_SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=request_is_https(request),
        path="/",
    )
    return {"ok": True}


@router.post("/api/admin/auth/logout")
async def admin_logout(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}