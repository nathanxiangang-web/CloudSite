"""X1 连接管理 Pydantic schemas。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ConnectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    base_url: str = Field(min_length=4, max_length=500)
    username: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=500)
    remember_credentials: bool = True
    provider_type: str = Field(default="generic_alist", max_length=40)


class ConnectionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    base_url: str | None = Field(default=None, min_length=4, max_length=500)
    username: str | None = Field(default=None, min_length=1, max_length=200)
    password: str | None = Field(default=None, max_length=500)
    remember_credentials: bool | None = None
    provider_type: str | None = Field(default=None, max_length=40)


class ConnectionToggle(BaseModel):
    enabled: bool


class CompatRecordCreate(BaseModel):
    provider_type: str = Field(min_length=1, max_length=40)
    adapter_version: str = Field(min_length=1, max_length=100)
    platform: str = Field(min_length=1, max_length=100)
    platform_version: str = Field(default="", max_length=100)
    test_result: str = Field(default="pass", pattern="^(pass|fail|partial)$")
    tested_capabilities_json: str = ""
    notes: str = ""