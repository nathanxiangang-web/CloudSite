import base64
import hmac
import json
import secrets
import time
from hashlib import sha256

from cloudsite.config import settings


SHARE_TICKET_TTL_SECONDS = 3600


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def create_share_ticket(
    token: str,
    code_version: int,
    *,
    share_expires_at: int | None = None,
    now: int | None = None,
) -> str:
    current = int(time.time()) if now is None else now
    expires_at = current + SHARE_TICKET_TTL_SECONDS
    if share_expires_at is not None:
        expires_at = min(expires_at, share_expires_at)
    payload = _b64encode(
        json.dumps(
            {
                "share_token": token,
                "code_version": code_version,
                "issued_at": current,
                "expires_at": expires_at,
                "nonce": secrets.token_urlsafe(12),
            },
            separators=(",", ":"),
        ).encode()
    )
    signature = hmac.new(settings.secret_key.encode(), payload.encode(), sha256).hexdigest()
    return f"{payload}.{signature}"


def validate_share_ticket(token: str, code_version: int, ticket: str | None, *, now: int | None = None) -> bool:
    if not ticket or "." not in ticket:
        return False
    payload, signature = ticket.rsplit(".", 1)
    expected = hmac.new(settings.secret_key.encode(), payload.encode(), sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return False
    try:
        decoded = json.loads(_b64decode(payload))
    except Exception:
        return False
    current = int(time.time()) if now is None else now
    return (
        decoded.get("share_token") == token
        and int(decoded.get("code_version", -1)) == code_version
        and int(decoded.get("expires_at", 0)) > current
    )


def share_cookie_name(token: str) -> str:
    digest = sha256(token.encode()).hexdigest()[:16]
    return f"cloudsite_share_{digest}"
