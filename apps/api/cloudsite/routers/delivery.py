"""T2 delivery package client routes.

Public endpoints for customers to view delivery packages and submit feedback.
Access is controlled by access_token and optional access_code.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..delivery_schemas import (
    DeliveryFeedbackRequest,
    PackageDetailResponse,
    PackageSummaryResponse,
    ItemResponse,
    VerifyAccessRequest,
)

router = APIRouter()


def _delivery_service():
    from ..services import delivery  # noqa: PLC0415

    return delivery


def _translate_error(exc: Exception) -> HTTPException:
    service = _delivery_service()
    if isinstance(exc, service.PackageNotFound):
        return HTTPException(404, {"code": "PACKAGE_NOT_FOUND", "message": str(exc)})
    if isinstance(exc, service.AccessDenied):
        return HTTPException(403, {"code": "ACCESS_DENIED", "message": str(exc)})
    return HTTPException(500, {"code": "DELIVERY_ERROR", "message": "交付服务错误"})


def _summary_to_response(s) -> PackageSummaryResponse:
    return PackageSummaryResponse(
        package_id=s.package_id,
        name=s.name,
        project_note=s.project_note,
        revision=s.revision,
        creator_user_id=s.creator_user_id,
        status=s.status,
        expires_at=s.expires_at,
        published_at=s.published_at,
        item_count=s.item_count,
        created_at=s.created_at,
        updated_at=s.updated_at,
    )


def _item_to_response(i) -> ItemResponse:
    return ItemResponse(
        item_id=i.item_id,
        package_id=i.package_id,
        asset_id=i.asset_id,
        resource_id=i.resource_id,
        display_name=i.display_name,
        bound_checksum=i.bound_checksum,
        bound_checksum_algorithm=i.bound_checksum_algorithm,
        bound_size=i.bound_size,
        sort_order=i.sort_order,
        note=i.note,
        changed=i.changed,
    )


@router.get("/api/delivery/{access_token}", response_model=PackageDetailResponse)
async def view_delivery(access_token: str, code: str | None = None):
    from ..main import StateSession

    service = _delivery_service()
    async with StateSession() as state:
        try:
            package = await service.verify_access(state, access_token, access_code=code)
            detail = await service.get_package_detail(state, package.package_id)
            return PackageDetailResponse(
                package=_summary_to_response(detail.package),
                items=[_item_to_response(i) for i in detail.items],
            )
        except Exception as exc:
            raise _translate_error(exc)


@router.post("/api/delivery/{access_token}/feedback")
async def submit_feedback(access_token: str, body: DeliveryFeedbackRequest, code: str | None = None):
    from ..main import StateSession
    from ..models import OperationLog

    service = _delivery_service()
    async with StateSession() as state:
        try:
            package = await service.verify_access(state, access_token, access_code=code)
            state.add(OperationLog(
                level="INFO",
                module="delivery",
                action="feedback",
                message=f"Package {package.package_id}: {body.kind} - {body.message}",
            ))
            await state.commit()
            return {"ok": True}
        except Exception as exc:
            await state.rollback()
            raise _translate_error(exc)