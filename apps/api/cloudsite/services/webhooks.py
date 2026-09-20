"""X2 Webhook service.

Event dispatch with signing, retry, dedup via event_id, and failure queue.
Core events: entry.created, release.published, asset.unavailable, review.completed.

Transaction ownership stays with the caller.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import WebhookDelivery, WebhookEndpoint, utcnow

ENDPOINT_ID_PREFIX = "wh_"
DELIVERY_ID_PREFIX = "wd_"
_ID_HEX_LEN = 32

EVENT_ENTRY_CREATED = "entry.created"
EVENT_RELEASE_PUBLISHED = "release.published"
EVENT_ASSET_UNAVAILABLE = "asset.unavailable"
EVENT_REVIEW_COMPLETED = "review.completed"

CORE_EVENT_TYPES = [
    EVENT_ENTRY_CREATED,
    EVENT_RELEASE_PUBLISHED,
    EVENT_ASSET_UNAVAILABLE,
    EVENT_REVIEW_COMPLETED,
]

DEFAULT_RETRY_DELAY_SECONDS = 60


class WebhookError(Exception):
    """Webhook error base class."""


class EndpointNotFound(WebhookError):
    def __init__(self, endpoint_id: str):
        super().__init__(f"Webhook endpoint {endpoint_id} not found")


@dataclass(frozen=True, slots=True)
class EndpointSummary:
    endpoint_id: str
    url: str
    event_types: list[str]
    status: str
    max_retries: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class DeliverySummary:
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


def _new_id(prefix: str) -> str:
    return prefix + secrets.token_hex(_ID_HEX_LEN // 2)


def _new_event_id() -> str:
    return secrets.token_hex(16)


def sign_payload(secret: str, payload: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


async def create_endpoint(
    state: AsyncSession,
    url: str,
    secret: str = "",
    event_types: list[str] | None = None,
    max_retries: int = 3,
) -> WebhookEndpoint:
    endpoint = WebhookEndpoint(
        endpoint_id=_new_id(ENDPOINT_ID_PREFIX),
        url=url,
        secret=secret or secrets.token_urlsafe(32),
        event_types=json.dumps(event_types or []),
        max_retries=max_retries,
    )
    state.add(endpoint)
    await state.flush()
    return endpoint


async def list_endpoints(state: AsyncSession, status: str | None = None) -> list[EndpointSummary]:
    stmt = select(WebhookEndpoint).order_by(WebhookEndpoint.created_at.desc())
    if status:
        stmt = stmt.where(WebhookEndpoint.status == status)
    result = await state.execute(stmt)
    endpoints = result.scalars().all()
    return [
        EndpointSummary(
            endpoint_id=e.endpoint_id,
            url=e.url,
            event_types=json.loads(e.event_types),
            status=e.status,
            max_retries=e.max_retries,
            created_at=e.created_at,
            updated_at=e.updated_at,
        )
        for e in endpoints
    ]


async def get_endpoint(state: AsyncSession, endpoint_id: str) -> WebhookEndpoint:
    endpoint = await state.get(WebhookEndpoint, endpoint_id)
    if not endpoint:
        raise EndpointNotFound(endpoint_id)
    return endpoint


async def update_endpoint(
    state: AsyncSession,
    endpoint_id: str,
    url: str | None = None,
    event_types: list[str] | None = None,
    status: str | None = None,
    max_retries: int | None = None,
) -> WebhookEndpoint:
    endpoint = await get_endpoint(state, endpoint_id)
    if url is not None:
        endpoint.url = url
    if event_types is not None:
        endpoint.event_types = json.dumps(event_types)
    if status is not None:
        endpoint.status = status
    if max_retries is not None:
        endpoint.max_retries = max_retries
    endpoint.updated_at = utcnow()
    await state.flush()
    return endpoint


async def delete_endpoint(state: AsyncSession, endpoint_id: str) -> None:
    endpoint = await get_endpoint(state, endpoint_id)
    await state.delete(endpoint)
    await state.flush()


async def dispatch_event(
    state: AsyncSession,
    event_type: str,
    event_data: dict,
    event_id: str | None = None,
) -> list[WebhookDelivery]:
    eid = event_id or _new_event_id()
    payload = json.dumps({"event_id": eid, "event_type": event_type, "data": event_data})

    stmt = select(WebhookEndpoint).where(WebhookEndpoint.status == "active")
    result = await state.execute(stmt)
    endpoints = result.scalars().all()

    deliveries: list[WebhookDelivery] = []
    for ep in endpoints:
        types = json.loads(ep.event_types)
        if event_type not in types and "*" not in types:
            continue

        existing = await state.execute(
            select(WebhookDelivery).where(
                WebhookDelivery.endpoint_id == ep.endpoint_id,
                WebhookDelivery.event_id == eid,
            )
        )
        if existing.scalar_one_or_none():
            continue

        delivery = WebhookDelivery(
            delivery_id=_new_id(DELIVERY_ID_PREFIX),
            endpoint_id=ep.endpoint_id,
            event_id=eid,
            event_type=event_type,
            payload=payload,
            status="pending",
        )
        state.add(delivery)
        deliveries.append(delivery)

    await state.flush()
    return deliveries


async def list_deliveries(
    state: AsyncSession,
    endpoint_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[DeliverySummary]:
    stmt = select(WebhookDelivery).order_by(WebhookDelivery.created_at.desc())
    if endpoint_id:
        stmt = stmt.where(WebhookDelivery.endpoint_id == endpoint_id)
    if status:
        stmt = stmt.where(WebhookDelivery.status == status)
    stmt = stmt.limit(limit)
    result = await state.execute(stmt)
    deliveries = result.scalars().all()
    return [
        DeliverySummary(
            delivery_id=d.delivery_id,
            endpoint_id=d.endpoint_id,
            event_id=d.event_id,
            event_type=d.event_type,
            status=d.status,
            attempts=d.attempts,
            response_code=d.response_code,
            next_retry_at=d.next_retry_at,
            created_at=d.created_at,
            updated_at=d.updated_at,
        )
        for d in deliveries
    ]


async def mark_delivered(
    state: AsyncSession,
    delivery_id: str,
    response_code: int,
    response_body: str = "",
) -> WebhookDelivery:
    delivery = await state.get(WebhookDelivery, delivery_id)
    if not delivery:
        raise WebhookError(f"Delivery {delivery_id} not found")
    delivery.status = "delivered" if 200 <= response_code < 300 else "failed"
    delivery.response_code = response_code
    delivery.response_body = response_body[:1000]
    delivery.attempts += 1
    delivery.updated_at = utcnow()
    await state.flush()
    return delivery


async def mark_failed(
    state: AsyncSession,
    delivery_id: str,
    response_code: int | None = None,
    response_body: str = "",
) -> WebhookDelivery:
    delivery = await state.get(WebhookDelivery, delivery_id)
    if not delivery:
        raise WebhookError(f"Delivery {delivery_id} not found")
    delivery.status = "failed"
    delivery.response_code = response_code
    delivery.response_body = response_body[:1000]
    delivery.attempts += 1
    delivery.next_retry_at = utcnow() + timedelta(seconds=DEFAULT_RETRY_DELAY_SECONDS)
    delivery.updated_at = utcnow()
    await state.flush()
    return delivery


async def get_pending_deliveries(state: AsyncSession, limit: int = 50) -> list[WebhookDelivery]:
    stmt = (
        select(WebhookDelivery)
        .where(WebhookDelivery.status.in_(["pending", "failed"]))
        .order_by(WebhookDelivery.created_at)
        .limit(limit)
    )
    result = await state.execute(stmt)
    return list(result.scalars().all())