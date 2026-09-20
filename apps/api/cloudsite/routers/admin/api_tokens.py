"""X2 API Token + Webhook admin routes.

Registered under /api/admin/api-tokens/ and /api/admin/webhooks/ —
automatically protected by admin_session_middleware.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query

from ...api_schemas import (
    CreateEndpointRequest,
    CreateTokenRequest,
    DeliveryListResponse,
    DeliveryResponse,
    DispatchEventRequest,
    DispatchResponse,
    EndpointListResponse,
    EndpointResponse,
    TokenCreatedResponse,
    TokenListResponse,
    TokenSummaryResponse,
    UpdateEndpointRequest,
)

router = APIRouter()


def _token_service():
    from ...services import api_tokens  # noqa: PLC0415

    return api_tokens


def _webhook_service():
    from ...services import webhooks  # noqa: PLC0415

    return webhooks


def _token_summary_to_response(s) -> TokenSummaryResponse:
    return TokenSummaryResponse(
        token_id=s.token_id,
        label=s.label,
        scopes=s.scopes,
        status=s.status,
        created_by=s.created_by,
        expires_at=s.expires_at,
        last_used_at=s.last_used_at,
        created_at=s.created_at,
        updated_at=s.updated_at,
    )


def _endpoint_to_response(e) -> EndpointResponse:
    return EndpointResponse(
        endpoint_id=e.endpoint_id,
        url=e.url,
        event_types=json.loads(e.event_types),
        status=e.status,
        max_retries=e.max_retries,
        created_at=e.created_at,
        updated_at=e.updated_at,
    )


def _delivery_to_response(d) -> DeliveryResponse:
    return DeliveryResponse(
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


# ---- API Token routes ----

@router.post("/api/admin/api-tokens", response_model=TokenCreatedResponse)
async def create_token(body: CreateTokenRequest):
    from ...main import StateSession

    service = _token_service()
    async with StateSession() as state:
        raw_token, token = await service.create_token(
            state,
            label=body.label,
            scopes=body.scopes,
            expires_at=body.expires_at,
        )
        await state.commit()
        return TokenCreatedResponse(
            token_id=token.token_id,
            raw_token=raw_token,
            label=token.label,
            scopes=json.loads(token.scopes),
            status=token.status,
            created_at=token.created_at,
        )


@router.get("/api/admin/api-tokens", response_model=TokenListResponse)
async def list_tokens(status: str | None = Query(default=None)):
    from ...main import StateSession

    service = _token_service()
    async with StateSession() as state:
        tokens = await service.list_tokens(state, status=status)
        return TokenListResponse(tokens=[_token_summary_to_response(t) for t in tokens])


@router.delete("/api/admin/api-tokens/{token_id}")
async def revoke_token(token_id: str):
    from ...main import StateSession

    service = _token_service()
    async with StateSession() as state:
        try:
            await service.revoke_token(state, token_id)
            await state.commit()
            return {"ok": True}
        except Exception as exc:
            await state.rollback()
            if isinstance(exc, service.TokenNotFound):
                raise HTTPException(404, {"code": "TOKEN_NOT_FOUND", "message": str(exc)})
            raise HTTPException(500, {"code": "TOKEN_ERROR", "message": str(exc)})


# ---- Webhook routes ----

@router.post("/api/admin/webhooks", response_model=EndpointResponse)
async def create_webhook(body: CreateEndpointRequest):
    from ...main import StateSession

    service = _webhook_service()
    async with StateSession() as state:
        endpoint = await service.create_endpoint(
            state,
            url=body.url,
            secret=body.secret,
            event_types=body.event_types,
            max_retries=body.max_retries,
        )
        await state.commit()
        return _endpoint_to_response(endpoint)


@router.get("/api/admin/webhooks", response_model=EndpointListResponse)
async def list_webhooks(status: str | None = Query(default=None)):
    from ...main import StateSession

    service = _webhook_service()
    async with StateSession() as state:
        endpoints = await service.list_endpoints(state, status=status)
        return EndpointListResponse(
            endpoints=[
                EndpointResponse(
                    endpoint_id=e.endpoint_id,
                    url=e.url,
                    event_types=e.event_types,
                    status=e.status,
                    max_retries=e.max_retries,
                    created_at=e.created_at,
                    updated_at=e.updated_at,
                )
                for e in endpoints
            ]
        )


@router.put("/api/admin/webhooks/{endpoint_id}", response_model=EndpointResponse)
async def update_webhook(endpoint_id: str, body: UpdateEndpointRequest):
    from ...main import StateSession

    service = _webhook_service()
    async with StateSession() as state:
        try:
            endpoint = await service.update_endpoint(
                state,
                endpoint_id,
                url=body.url,
                event_types=body.event_types,
                status=body.status,
                max_retries=body.max_retries,
            )
            await state.commit()
            return _endpoint_to_response(endpoint)
        except Exception as exc:
            await state.rollback()
            if isinstance(exc, service.EndpointNotFound):
                raise HTTPException(404, {"code": "ENDPOINT_NOT_FOUND", "message": str(exc)})
            raise HTTPException(500, {"code": "WEBHOOK_ERROR", "message": str(exc)})


@router.delete("/api/admin/webhooks/{endpoint_id}")
async def delete_webhook(endpoint_id: str):
    from ...main import StateSession

    service = _webhook_service()
    async with StateSession() as state:
        try:
            await service.delete_endpoint(state, endpoint_id)
            await state.commit()
            return {"ok": True}
        except Exception as exc:
            await state.rollback()
            if isinstance(exc, service.EndpointNotFound):
                raise HTTPException(404, {"code": "ENDPOINT_NOT_FOUND", "message": str(exc)})
            raise HTTPException(500, {"code": "WEBHOOK_ERROR", "message": str(exc)})


@router.post("/api/admin/webhooks/dispatch", response_model=DispatchResponse)
async def dispatch_event(body: DispatchEventRequest):
    from ...main import StateSession

    service = _webhook_service()
    async with StateSession() as state:
        deliveries = await service.dispatch_event(
            state,
            event_type=body.event_type,
            event_data=body.event_data,
            event_id=body.event_id,
        )
        await state.commit()
        return DispatchResponse(dispatched_count=len(deliveries))


@router.get("/api/admin/webhooks/{endpoint_id}/deliveries", response_model=DeliveryListResponse)
async def list_deliveries(
    endpoint_id: str,
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
):
    from ...main import StateSession

    service = _webhook_service()
    async with StateSession() as state:
        deliveries = await service.list_deliveries(
            state,
            endpoint_id=endpoint_id,
            status=status,
            limit=limit,
        )
        return DeliveryListResponse(
            deliveries=[
                DeliveryResponse(
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
        )