"""HTTP 中间件：CORS 与管理员会话守卫。

admin_session_middleware 内部通过 ``cloudsite.main`` 引用 StateSession 与
SESSION_COOKIE，以兼容测试中 monkeypatch main.StateSession 的用法。
"""
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ..admin_auth import (
    get_setup_completed,
    is_public_admin_endpoint,
    should_block_admin_request,
)
from ..auth import validate_request_origin
from ..config import settings
from ..preview import validate_preview_ticket
from ..sessions import (
    USER_SESSION_COOKIE,
    SessionValidationError,
    validate_user_session,
)


def register_cors(app) -> None:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


async def admin_session_middleware(request: Request, call_next):
    from cloudsite import main

    path = request.url.path
    if request.method == "OPTIONS":
        return await call_next(request)

    if path.startswith("/api/admin"):
        # M4: 精确公开端点放行（写操作仍做同源校验）
        if is_public_admin_endpoint(request.method, path):
            if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
                try:
                    validate_request_origin(request)
                except Exception:
                    return JSONResponse(
                        {"detail": {"code": "ORIGIN_FORBIDDEN", "message": "请求来源校验失败"}},
                        status_code=403,
                    )
            return await call_next(request)
        # M4: 统一失败关闭判定
        async with main.StateSession() as session:
            setup_completed = await get_setup_completed(session)
        admin_authenticated = main.verify_session_token(request.cookies.get(main.SESSION_COOKIE))
        block, error_code = should_block_admin_request(
            method=request.method,
            path=path,
            setup_completed=setup_completed,
            admin_cookie_valid=admin_authenticated,
        )
        if block:
            if error_code == "SETUP_REQUIRED":
                return JSONResponse(
                    {"detail": {"code": "SETUP_REQUIRED", "message": "站点尚未完成初始化"}},
                    status_code=409,
                )
            return JSONResponse(
                {"detail": {"code": "ADMIN_REQUIRED", "message": "请先登录管理后台"}},
                status_code=403,
            )
        # M6: 后台写操作同源校验
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            try:
                validate_request_origin(request)
            except Exception:
                return JSONResponse(
                    {"detail": {"code": "ORIGIN_FORBIDDEN", "message": "请求来源校验失败"}},
                    status_code=403,
                )
        return await call_next(request)

    public_api_paths = {"/api/health", "/api/auth/login", "/api/auth/register", "/api/site"}
    preview_ticket_valid = False
    if path.startswith("/p/"):
        resource_id = path.removeprefix("/p/")
        preview_ticket_valid = validate_preview_ticket(resource_id, request.query_params.get("ticket"))
    requires_user = not preview_ticket_valid and (
        (
            path.startswith("/api/")
            and path not in public_api_paths
            and not path.startswith("/api/public/shares/")
            and not path.startswith("/api/public/share-page")
        )
        or path.startswith("/d/")
        or (path.startswith("/p/") and not path.startswith("/s/"))
        or path.startswith("/office-files/")
    )
    if not requires_user:
        return await call_next(request)
    async with main.StateSession() as session:
        try:
            await validate_user_session(session, request.cookies.get(USER_SESSION_COOKIE))
            await session.commit()
        except SessionValidationError as exc:
            await session.commit()
            return JSONResponse(
                {"detail": {"code": exc.code, "message": exc.message}},
                status_code=exc.status_code,
            )
    return await call_next(request)


def register_middlewares(app) -> None:
    register_cors(app)
    app.middleware("http")(admin_session_middleware)