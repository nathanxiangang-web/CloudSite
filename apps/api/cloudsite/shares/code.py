"""Compatibility facade for Shares code primitives."""

from cloudsite.config import settings
from cloudsite.modules.shares.domain.code import (
    SHARE_CODE_ALPHABET,
    SHARE_CODE_LENGTH,
    generate_share_code,
    hash_share_code as _hash_share_code,
    normalize_share_code,
    valid_share_code,
    verify_share_code as _verify_share_code,
)


def hash_share_code(token: str, code: str) -> str:
    return _hash_share_code(
        token,
        code,
        secret_key=settings.secret_key,
    )


def verify_share_code(
    token: str,
    code: str,
    code_hash: str | None,
) -> bool:
    return _verify_share_code(
        token,
        code,
        code_hash,
        secret_key=settings.secret_key,
    )


__all__ = [
    "SHARE_CODE_ALPHABET",
    "SHARE_CODE_LENGTH",
    "generate_share_code",
    "normalize_share_code",
    "valid_share_code",
    "hash_share_code",
    "verify_share_code",
]
