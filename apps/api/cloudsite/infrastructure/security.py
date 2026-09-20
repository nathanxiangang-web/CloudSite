"""管理员会话令牌生成与校验。

Cookie 有效期统一为 7 天（604800 秒），管理员与用户保持一致。
"""
import base64
import hashlib
import hmac
import json
import logging
import time

from ..config import settings

ADMIN_SESSION_MAX_AGE_SECONDS = 7 * 24 * 60 * 60
logger = logging.getLogger(__name__)

_INSECURE_SECRET_VALUES = {
    "cloudsite-development-key-change-me",
    "replace-with-a-long-random-secret",
    "change-me",
}


def validate_production_secrets() -> None:
    if settings.allow_insecure_dev_key:
        return
    key = settings.secret_key
    if not key or key in _INSECURE_SECRET_VALUES:
        raise RuntimeError(
            "CLOUDSITE_SECRET_KEY 未设置或使用了公开占位值，拒绝启动。"
            "请生成随机密钥：python -c \"import secrets; print(secrets.token_urlsafe(48))\""
        )
    if len(key) < 32:
        raise RuntimeError("CLOUDSITE_SECRET_KEY 长度不足 32 字符，拒绝启动。")
    if not settings.master_key:
        logger.warning("CLOUDSITE_MASTER_KEY 未设置，凭据加密将回退到 SECRET_KEY。生产环境建议显式设置独立 MASTER_KEY。")


def create_session_token(username: str) -> str:
    payload = base64.urlsafe_b64encode(
        json.dumps(
            {"username": username, "expires": int(time.time()) + ADMIN_SESSION_MAX_AGE_SECONDS},
            separators=(",", ":"),
        ).encode()
    ).decode().rstrip("=")
    signature = hmac.new(settings.secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def verify_session_token(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    payload, signature = token.rsplit(".", 1)
    expected = hmac.new(settings.secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return False
    try:
        decoded = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return int(decoded.get("expires", 0)) > int(time.time())
    except Exception:
        return False