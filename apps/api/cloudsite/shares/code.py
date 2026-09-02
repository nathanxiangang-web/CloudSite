import hmac
import secrets
from hashlib import sha256

from cloudsite.config import settings


SHARE_CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
SHARE_CODE_LENGTH = 4


def generate_share_code() -> str:
    return "".join(secrets.choice(SHARE_CODE_ALPHABET) for _ in range(SHARE_CODE_LENGTH))


def normalize_share_code(value: str) -> str:
    return value.strip().upper()


def valid_share_code(value: str) -> bool:
    normalized = normalize_share_code(value)
    return len(normalized) == SHARE_CODE_LENGTH and all(character in SHARE_CODE_ALPHABET for character in normalized)


def hash_share_code(token: str, code: str) -> str:
    normalized = normalize_share_code(code)
    payload = f"{token}:{normalized}".encode()
    return hmac.new(settings.secret_key.encode(), payload, sha256).hexdigest()


def verify_share_code(token: str, code: str, code_hash: str | None) -> bool:
    if not code_hash or not valid_share_code(code):
        return False
    return hmac.compare_digest(hash_share_code(token, code), code_hash)
