"""admin/alist 路由：AList 连接配置。"""
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from ...alist import AListClient, AListError
from ...crypto import decrypt_secret, encrypt_secret
from ...models import AListConnection, OperationLog, utcnow
from ...schemas import AListInput

router = APIRouter()


def alist_http_exception(exc: Exception, fallback_status: int = 502) -> HTTPException:
    if isinstance(exc, AListError):
        return HTTPException(exc.status_code, {"code": exc.code, "message": str(exc)})
    if isinstance(exc, ValueError):
        return HTTPException(400, {"code": "AL-006", "message": str(exc)})
    return HTTPException(fallback_status, {"code": "AL-999", "message": "AList 操作失败，请稍后重试"})


@router.get("/api/admin/alist")
async def get_alist():
    from ...main import StateSession

    async with StateSession() as session:
        row = await session.get(AListConnection, 1)
        if not row:
            return {"base_url": "", "username": "", "remember_credentials": True, "enabled": False, "connection_status": "unconfigured", "last_test_status": "untested", "last_test_message": "", "last_test_at": None, "has_password": False}
        return {"base_url": row.base_url, "username": row.username, "remember_credentials": row.remember_credentials, "enabled": row.enabled, "connection_status": "connected" if row.enabled and row.last_test_status == "success" else "disconnected", "last_test_status": row.last_test_status, "last_test_message": row.last_test_message, "last_test_at": row.last_test_at, "has_password": bool(row.password_ciphertext)}


@router.post("/api/admin/alist/test")
async def test_alist(payload: AListInput):
    from ...main import StateSession

    async with StateSession() as session:
        row = await session.get(AListConnection, 1)
        password = payload.password
        try:
            if not password and row and row.password_ciphertext:
                password = decrypt_secret(row.password_ciphertext)
            if not password:
                raise AListError("请输入 AList 密码", "AL-004", status_code=400, auth_failed=True)
            result = await AListClient(payload.base_url, payload.username, password).test()
        except Exception as exc:
            status_row = row or AListConnection(id=1)
            status_row.last_test_status = "failed"
            status_row.last_test_message = str(exc)
            status_row.last_test_at = utcnow()
            session.add(status_row)
            session.add(OperationLog(level="ERROR", module="alist", action="test", message=f"AList 连接测试失败：{str(exc)[:300]}"))
            await session.commit()
            raise alist_http_exception(exc, 400) from exc
        status_row = row or AListConnection(id=1)
        status_row.last_test_status = "success"
        status_row.last_test_message = result["message"]
        status_row.last_test_at = utcnow()
        status_row.base_path = result.get("base_path") or "/"
        session.add(status_row)
        session.add(OperationLog(module="alist", action="test", message=f"AList 连接测试成功，根目录包含 {result['item_count']} 项"))
        await session.commit()
        return result


@router.put("/api/admin/alist")
async def save_alist(payload: AListInput):
    from ...main import StateSession

    async with StateSession() as session:
        row = await session.get(AListConnection, 1) or AListConnection(id=1)
        password = payload.password
        if not password and row.password_ciphertext:
            try:
                password = decrypt_secret(row.password_ciphertext)
            except ValueError as exc:
                raise alist_http_exception(exc, 400) from exc
        if not password:
            raise HTTPException(400, "请输入 AList 密码")
        try:
            result = await AListClient(payload.base_url, payload.username, password).test()
        except Exception as exc:
            row.last_test_status = "failed"
            row.last_test_message = str(exc)
            row.last_test_at = utcnow()
            session.add(row)
            await session.commit()
            session.add(OperationLog(level="ERROR", module="alist", action="save", message=f"AList 设置验证失败：{str(exc)[:300]}"))
            await session.commit()
            raise alist_http_exception(exc, 400) from exc
        row.base_url = payload.base_url.rstrip("/")
        row.base_path = result.get("base_path") or "/"
        row.username = payload.username
        row.password_ciphertext = encrypt_secret(password) if payload.remember_credentials else ""
        row.remember_credentials = payload.remember_credentials
        row.enabled = True
        row.last_test_status = "success"
        row.last_test_message = "AList 连接及根目录访问成功"
        row.last_test_at = utcnow()
        session.add(row)
        session.add(OperationLog(module="alist", action="save", message="AList 连接设置已验证并保存"))
        await session.commit()
        return {"ok": True, "message": "AList 设置已保存"}


@router.get("/api/admin/alist/directories")
async def browse_alist_directories(path: str = Query("/", min_length=1, max_length=1000)):
    from ...main import StateSession

    normalized_path = "/" + path.strip().strip("/")
    if normalized_path == "//":
        normalized_path = "/"
    async with StateSession() as session:
        row = await session.get(AListConnection, 1)
    if not row or not row.enabled:
        raise HTTPException(409, "请先连接并保存 AList 设置")
    if not row.password_ciphertext:
        raise HTTPException(409, "当前未保存 AList 登录凭据，请重新保存连接并启用记住登录信息")
    try:
        client = AListClient(row.base_url, row.username, decrypt_secret(row.password_ciphertext))
        directories = await client.list_directories(normalized_path)
    except Exception as exc:
        raise alist_http_exception(exc) from exc

    def directory_path(name: str) -> str:
        return f"/{name}" if normalized_path == "/" else f"{normalized_path}/{name}"

    parent_path = "/" if normalized_path == "/" else normalized_path.rsplit("/", 1)[0] or "/"
    return {
        "path": normalized_path,
        "parent_path": parent_path,
        "items": [
            {
                "name": str(item["name"]),
                "path": directory_path(str(item["name"])),
                "modified": item.get("modified"),
            }
            for item in directories
        ],
    }