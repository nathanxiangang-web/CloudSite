"""admin/setup 路由：站点一次性初始化。"""
from fastapi import APIRouter, HTTPException, Request

from ...admin_auth import get_setup_completed, verify_setup_token
from ...alist import AListClient
from ...config import settings
from ...crypto import encrypt_secret
from ...models import AListConnection, OperationLog, SystemSetting, utcnow
from ...auth import validate_request_origin
from ...schemas import AListInput

router = APIRouter()


@router.get("/api/admin/setup/status")
async def admin_setup_status():
    from ...main import StateSession

    async with StateSession() as session:
        setup_completed = await get_setup_completed(session)
    return {
        "setup_required": not setup_completed,
        "setup_available": bool(settings.setup_token),
    }


@router.post("/api/admin/setup/alist")
async def admin_setup_alist(payload: AListInput, request: Request):
    from ...main import StateSession, _alist_connection_cache

    # M3: 一次性初始化，固定处理顺序
    # 1. 同源校验（中间件已对公开写端点执行，这里二次确认）
    try:
        validate_request_origin(request)
    except Exception:
        raise HTTPException(403, {"code": "ORIGIN_FORBIDDEN", "message": "请求来源校验失败"})
    # 2. 检查是否仍为 setup_required
    async with StateSession() as session:
        setup_completed = await get_setup_completed(session)
        if setup_completed:
            raise HTTPException(409, {"code": "SETUP_ALREADY_COMPLETED", "message": "站点已完成初始化"})
        # 3. 检查初始化令牌
        if not settings.setup_token:
            raise HTTPException(503, {"code": "SETUP_UNAVAILABLE", "message": "服务器未配置初始化令牌"})
        provided_token = request.headers.get("X-CloudSite-Setup-Token", "")
        if not verify_setup_token(provided_token, settings.setup_token):
            raise HTTPException(403, {"code": "SETUP_FORBIDDEN", "message": "初始化令牌错误"})
        # 4. 校验请求字段（AListInput 已由 Pydantic 完成）
        # 5. 使用提交的配置测试 AList 登录
        try:
            result = await AListClient(payload.base_url, payload.username, payload.password).test()
        except Exception as exc:
            raise HTTPException(400, {"code": "ALIST_TEST_FAILED", "message": f"AList 验证失败：{str(exc)[:200]}"}) from exc
        # 6. 测试成功后保存 AList 配置 + 写入 setup_completed（同一事务）
        row = await session.get(AListConnection, 1) or AListConnection(id=1)
        row.base_url = payload.base_url.rstrip("/")
        row.base_path = result.get("base_path") or "/"
        row.username = payload.username
        row.password_ciphertext = encrypt_secret(payload.password) if payload.remember_credentials else ""
        row.remember_credentials = payload.remember_credentials
        row.enabled = True
        row.last_test_status = "success"
        row.last_test_message = "初始化时 AList 连接验证成功"
        row.last_test_at = utcnow()
        session.add(row)
        session.add(SystemSetting(key="setup_completed", value="true", value_type="string"))
        session.add(OperationLog(module="setup", action="alist_init", message="一次性初始化完成，AList 配置已保存"))
        await session.commit()
    # 7. 清理 AList 配置缓存
    _alist_connection_cache["data"] = None
    _alist_connection_cache["fetched_at"] = 0.0
    return {"setup_completed": True, "next": "/admin/login"}