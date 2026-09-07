"""全局异常处理器：将 HTTP/校验/未捕获异常统一转为结构化 JSON 响应。"""
import logging

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("cloudsite.main")


async def structured_http_error(_: Request, exc: StarletteHTTPException):
    if isinstance(exc.detail, dict) and isinstance(exc.detail.get("code"), str):
        detail = {
            "code": exc.detail["code"],
            "message": str(exc.detail.get("message") or "请求失败"),
        }
        for key, value in exc.detail.items():
            if key not in detail:
                detail[key] = value
    else:
        detail = {
            "code": f"HTTP_{exc.status_code}",
            "message": str(exc.detail or "请求失败"),
        }
    return JSONResponse({"detail": detail}, status_code=exc.status_code, headers=exc.headers)


async def structured_validation_error(_: Request, __: RequestValidationError):
    return JSONResponse(
        {"detail": {"code": "VALIDATION_ERROR", "message": "请求参数格式不正确"}},
        status_code=422,
    )


async def structured_internal_error(request: Request, exc: Exception):
    logger.error(
        "Unhandled API error on %s %s",
        request.method,
        request.url.path,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return JSONResponse(
        {"detail": {"code": "INTERNAL_ERROR", "message": "服务器暂时无法处理请求"}},
        status_code=500,
    )


def register_exception_handlers(app) -> None:
    app.add_exception_handler(StarletteHTTPException, structured_http_error)
    app.add_exception_handler(RequestValidationError, structured_validation_error)
    app.add_exception_handler(Exception, structured_internal_error)