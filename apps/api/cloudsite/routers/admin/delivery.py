"""T2 delivery package admin routes.

Registered under /api/admin/delivery-packages/ — automatically protected by
admin_session_middleware.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ...delivery_schemas import (
    AddItemRequest,
    CreatePackageRequest,
    ExportResponse,
    ItemResponse,
    PackageDetailResponse,
    PackageListResponse,
    PackageSummaryResponse,
)

router = APIRouter()


def _delivery_service():
    from ...services import delivery  # noqa: PLC0415

    return delivery


def _translate_error(exc: Exception) -> HTTPException:
    service = _delivery_service()
    if isinstance(exc, service.PackageNotFound):
        return HTTPException(404, {"code": "PACKAGE_NOT_FOUND", "message": str(exc)})
    if isinstance(exc, service.ItemNotFound):
        return HTTPException(404, {"code": "ITEM_NOT_FOUND", "message": str(exc)})
    if isinstance(exc, service.PackageStateInvalid):
        return HTTPException(409, {"code": "PACKAGE_STATE_INVALID", "message": str(exc)})
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


@router.post("/api/admin/delivery-packages", response_model=PackageSummaryResponse)
async def create_package(body: CreatePackageRequest):
    from ...main import StateSession

    service = _delivery_service()
    async with StateSession() as state:
        try:
            package = await service.create_package(
                state,
                name=body.name,
                project_note=body.project_note,
                access_code=body.access_code,
                expires_at=body.expires_at,
            )
            await state.commit()
            from sqlalchemy import func
            item_count = 0
            return PackageSummaryResponse(
                package_id=package.package_id,
                name=package.name,
                project_note=package.project_note,
                revision=package.revision,
                creator_user_id=package.creator_user_id,
                status=package.status,
                expires_at=package.expires_at,
                published_at=package.published_at,
                item_count=item_count,
                created_at=package.created_at,
                updated_at=package.updated_at,
            )
        except Exception as exc:
            await state.rollback()
            raise _translate_error(exc)


@router.get("/api/admin/delivery-packages", response_model=PackageListResponse)
async def list_packages(
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    from ...main import StateSession

    service = _delivery_service()
    async with StateSession() as state:
        items, total = await service.list_packages(state, status=status, page=page, page_size=page_size)
        return PackageListResponse(
            items=[_summary_to_response(i) for i in items],
            total=total,
            page=page,
            page_size=page_size,
        )


@router.get("/api/admin/delivery-packages/{package_id}", response_model=PackageDetailResponse)
async def get_package(package_id: str):
    from ...main import StateSession

    service = _delivery_service()
    async with StateSession() as state:
        try:
            detail = await service.get_package_detail(state, package_id)
            return PackageDetailResponse(
                package=_summary_to_response(detail.package),
                items=[_item_to_response(i) for i in detail.items],
            )
        except Exception as exc:
            raise _translate_error(exc)


@router.post("/api/admin/delivery-packages/{package_id}/items", response_model=ItemResponse)
async def add_item(package_id: str, body: AddItemRequest):
    from ...main import StateSession

    service = _delivery_service()
    async with StateSession() as state:
        try:
            item = await service.add_item(
                state,
                package_id=package_id,
                asset_id=body.asset_id,
                resource_id=body.resource_id,
                display_name=body.display_name,
                note=body.note,
                sort_order=body.sort_order,
            )
            await state.commit()
            return ItemResponse(
                item_id=item.item_id,
                package_id=item.package_id,
                asset_id=item.asset_id,
                resource_id=item.resource_id,
                display_name=item.display_name,
                bound_checksum=item.bound_checksum,
                bound_checksum_algorithm=item.bound_checksum_algorithm,
                bound_size=item.bound_size,
                sort_order=item.sort_order,
                note=item.note,
                changed=False,
            )
        except Exception as exc:
            await state.rollback()
            raise _translate_error(exc)


@router.delete("/api/admin/delivery-packages/{package_id}/items/{item_id}")
async def remove_item(package_id: str, item_id: int):
    from ...main import StateSession

    service = _delivery_service()
    async with StateSession() as state:
        try:
            await service.remove_item(state, package_id, item_id)
            await state.commit()
            return {"ok": True}
        except Exception as exc:
            await state.rollback()
            raise _translate_error(exc)


@router.post("/api/admin/delivery-packages/{package_id}/publish", response_model=PackageSummaryResponse)
async def publish_package(package_id: str):
    from ...main import StateSession

    service = _delivery_service()
    async with StateSession() as state:
        try:
            package = await service.publish_package(state, package_id)
            await state.commit()
            detail = await service.get_package_detail(state, package_id)
            return _summary_to_response(detail.package)
        except Exception as exc:
            await state.rollback()
            raise _translate_error(exc)


@router.post("/api/admin/delivery-packages/{package_id}/cancel", response_model=PackageSummaryResponse)
async def cancel_package(package_id: str):
    from ...main import StateSession

    service = _delivery_service()
    async with StateSession() as state:
        try:
            package = await service.cancel_package(state, package_id)
            await state.commit()
            detail = await service.get_package_detail(state, package_id)
            return _summary_to_response(detail.package)
        except Exception as exc:
            await state.rollback()
            raise _translate_error(exc)


@router.get("/api/admin/delivery-packages/{package_id}/export", response_model=ExportResponse)
async def export_package(package_id: str):
    from ...main import StateSession

    service = _delivery_service()
    async with StateSession() as state:
        try:
            data = await service.export_package(state, package_id)
            return ExportResponse(data=data)
        except Exception as exc:
            raise _translate_error(exc)