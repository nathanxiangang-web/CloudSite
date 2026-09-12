"""X2 API Token + Webhook request/response models."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CreateTokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = ""
    scopes: list[str] = []
    expires_at: datetime | None = None


class TokenCreatedResponse(BaseModel):
    token_id: str
    raw_token: str
    label: str
    scopes: list[str]
    status: str
    created_at: datetime


class TokenSummaryResponse(BaseModel):
    token_id: str
    label: str
    scopes: list[str]
    status: str
    created_by: str
    expires_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TokenListResponse(BaseModel):
    tokens: list[TokenSummaryResponse]


class CreateEndpointRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=1, max_length=500)
    secret: str = ""
    event_types: list[str] = []
    max_retries: int = 3


class UpdateEndpointRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str | None = None
    event_types: list[str] | None = None
    status: str | None = None
    max_retries: int | None = None


class EndpointResponse(BaseModel):
    endpoint_id: str
    url: str
    event_types: list[str]
    status: str
    max_retries: int
    created_at: datetime
    updated_at: datetime


class EndpointListResponse(BaseModel):
    endpoints: list[EndpointResponse]


class DeliveryResponse(BaseModel):
    delivery_id: str
    endpoint_id: str
    event_id: str
    event_type: str
    status: str
    attempts: int
    response_code: int | None
    next_retry_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DeliveryListResponse(BaseModel):
    deliveries: list[DeliveryResponse]


class DispatchEventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_type: str = Field(min_length=1, max_length=64)
    event_data: dict = {}
    event_id: str | None = None


class DispatchResponse(BaseModel):
    dispatched_count: int