"""Users credential input policy shared by public/admin HTTP edges."""

from __future__ import annotations

import re


USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{2,16}$")


class CredentialPolicyError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def validate_username(
    username: str,
) -> tuple[str, str]:
    if (
        username != username.strip()
        or not USERNAME_PATTERN.fullmatch(username)
    ):
        raise CredentialPolicyError(
            "USERNAME_INVALID",
            "用户名须为 2～16 位，仅允许字母、数字、下划线和短横线",
        )
    return username, username.lower()


def validate_password(
    value: str,
    *,
    field_name: str = "密码",
) -> str:
    if len(value) < 8 or len(value) > 72:
        raise CredentialPolicyError(
            "PASSWORD_INVALID",
            f"{field_name}长度须为 8～72 位",
        )
    return value


__all__ = [
    "CredentialPolicyError",
    "USERNAME_PATTERN",
    "validate_password",
    "validate_username",
]
