"""管理员会话令牌生成与校验。

Cookie 有效期统一为 24 小时（86400 秒），管理员与用户保持一致。
"""
import base64
import hashlib
import hmac
import json
import time

from ..config import settings

ADMIN_SESSION_MAX_AGE_SECONDS = 86400


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