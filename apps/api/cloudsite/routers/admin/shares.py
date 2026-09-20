"""admin/shares 路由：分享管理。"""
from fastapi import APIRouter, HTTPException
from ...config import settings
from ...modules.collections.contracts.public import (
    CollectionNotFound,
    get_admin_collection,
)
from ...modules.resources.contracts.public import resource_queries
from ...modules.shares.contracts.public import (
    ShareNotFound,
    ShareValidationError,
    cancel_share as cancel_share_record,
    create_share as create_share_record,
    delete_share as delete_share_record,
    get_share,
    list_all_shares,
    reset_share_code as reset_share_code_record,
    restore_share as restore_share_record,
    share_payload,
    share_status as module_share_status,
    target_valid_for_share,
    update_share_duration as update_share_duration_record,
)
from ...modules.users.contracts.public import user_references
from ...schemas import ShareInput, ShareUpdate

router = APIRouter()


def _translate_share_module_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ShareNotFound):
        return HTTPException(
            404,
            {"code": "SHARE_NOT_FOUND", "message": "分享不存在"},
        )
    if isinstance(exc, ShareValidationError):
        return HTTPException(
            exc.status_code,
            {"code": exc.code, "message": exc.message},
        )
    return HTTPException(
        500,
        {"code": "SHARE_ERROR", "message": "分享服务错误"},
    )


@router.get("/api/admin/shares")
async def admin_shares():
    from ...main import StateSession, IndexSession

    async with StateSession() as state, IndexSession() as index:
        rows = await list_all_shares(state)

        resource_ids = [
            row.object_id
            for row in rows
            if row.object_type == "resource"
        ]
        folder_ids = list(
            dict.fromkeys(
                row.object_id
                for row in rows
                if row.object_type == "folder"
            )
        )
        collection_ids = list(
            dict.fromkeys(
                int(row.object_id)
                for row in rows
                if (
                    row.object_type == "collection"
                    and row.object_id.isdigit()
                )
            )
        )
        creator_ids = [
            row.creator_user_id
            for row in rows
            if row.creator_user_id is not None
        ]

        resources = await resource_queries(index).resource_references(
            resource_ids=resource_ids,
        )
        folder_names: dict[str, str] = {}
        for folder_id in folder_ids:
            folder = await resource_queries(index).admin_index_folder(
                folder_id=folder_id,
            )
            if folder is not None:
                folder_names[folder_id] = folder.name

        collection_names: dict[str, str] = {}
        for collection_id in collection_ids:
            try:
                collection = await get_admin_collection(
                    state,
                    index,
                    collection_id,
                )
            except CollectionNotFound:
                continue
            collection_names[str(collection_id)] = str(
                collection.get("name") or ""
            )

        creators = await user_references(
            state,
            user_ids=[
                int(user_id)
                for user_id in creator_ids
                if user_id is not None
            ],
        )

        items = []
        for row in rows:
            target_valid = await target_valid_for_share(
                state,
                index,
                row,
            )
            status = module_share_status(row, target_valid)
            target_name = None
            if row.object_type == "resource":
                resource = resources.get(row.object_id)
                target_name = (
                    resource.name
                    if resource is not None
                    else None
                )
            elif row.object_type == "folder":
                target_name = folder_names.get(row.object_id)
            elif row.object_type == "collection":
                target_name = collection_names.get(row.object_id)

            creator = (
                creators.get(row.creator_user_id)
                if row.creator_user_id is not None
                else None
            )
            items.append(
                share_payload(row)
                | {
                    "expired": status == "expired",
                    "status": status,
                    "target_name": target_name,
                    "creator_username": (
                        creator.username
                        if creator is not None
                        else None
                    ),
                }
            )
        return {"items": items}


@router.post("/api/admin/shares")
async def create_share(payload: ShareInput):
    from ...main import StateSession, IndexSession

    async with StateSession() as state, IndexSession() as index:
        try:
            created = await create_share_record(
                state,
                index,
                object_type=payload.object_type,
                object_id=payload.object_id,
                access_mode=payload.access_mode,
                duration=payload.duration,
                title=payload.title,
                secret_key=settings.secret_key,
            )
        except ShareValidationError as exc:
            raise _translate_share_module_error(exc) from exc
        await state.commit()
        return share_payload(created.share) | {"code": created.code}


@router.patch("/api/admin/shares/{token}")
async def update_share(token: str, payload: ShareUpdate):
    from ...main import StateSession

    async with StateSession() as session:
        try:
            row = await get_share(session, token)
            if row is None:
                raise ShareNotFound(token)
            if payload.action == "cancel" or payload.enabled is False:
                row = await cancel_share_record(session, token)
            elif payload.action == "restore" or payload.enabled is True:
                row = await restore_share_record(
                    session,
                    token,
                    duration=payload.duration,
                )
            elif payload.action in {"reset_code", "upgrade"}:
                row, code = await reset_share_code_record(
                    session,
                    token,
                    secret_key=settings.secret_key,
                )
                await session.commit()
                return share_payload(row) | {"code": code}
            if payload.duration:
                row = await update_share_duration_record(
                    session,
                    token,
                    duration=payload.duration,
                )
            await session.commit()
            return share_payload(row)
        except (ShareNotFound, ShareValidationError) as exc:
            raise _translate_share_module_error(exc) from exc


@router.delete("/api/admin/shares/{token}")
async def delete_share(token: str):
    from ...main import StateSession

    async with StateSession() as session:
        try:
            await delete_share_record(
                session,
                token,
                action="share_deleted",
                message=f"删除分享 {token}",
            )
            await session.commit()
            return {"ok": True}
        except ShareNotFound as exc:
            raise _translate_share_module_error(exc) from exc
