"""admin/shares 路由：分享管理。"""
from fastapi import APIRouter, HTTPException
from sqlalchemy import desc, select

from ...models import Collection, Folder, OperationLog, Resource, Share, User
from ...schemas import ShareInput, ShareUpdate
from ...services.shares import share_dict
from ...shares.service import (
    cancel_share as cancel_share_row,
    create_share as create_share_row,
    reset_share_code,
    restore_share,
    share_status,
    target_valid_for_share,
    update_share_duration,
)

router = APIRouter()


@router.get("/api/admin/shares")
async def admin_shares():
    from ...main import StateSession, IndexSession

    async with StateSession() as state, IndexSession() as index:
        rows = list((await state.scalars(select(Share).order_by(desc(Share.created_at)))).all())
        resource_ids = [row.object_id for row in rows if row.object_type == "resource"]
        folder_ids = [row.object_id for row in rows if row.object_type == "folder"]
        collection_ids = [int(row.object_id) for row in rows if row.object_type == "collection" and row.object_id.isdigit()]
        creator_ids = {row.creator_user_id for row in rows if row.creator_user_id is not None}
        names: dict[str, str] = {}
        creators = {
            row.id: row.username
            for row in (
                await state.scalars(select(User).where(User.id.in_(creator_ids)))
            ).all()
        } if creator_ids else {}
        if resource_ids:
            names.update({row.id: row.name for row in (await index.scalars(select(Resource).where(Resource.id.in_(resource_ids)))).all()})
        if folder_ids:
            names.update({row.id: row.name for row in (await index.scalars(select(Folder).where(Folder.id.in_(folder_ids)))).all()})
        if collection_ids:
            names.update({str(row.id): row.name for row in (await state.scalars(select(Collection).where(Collection.id.in_(collection_ids)))).all()})
        items = []
        for row in rows:
            target_valid = await target_valid_for_share(state, index, row)
            status = share_status(row, target_valid)
            items.append(
                share_dict(row)
                | {
                    "expired": status == "expired",
                    "status": status,
                    "target_name": names.get(row.object_id),
                    "creator_username": creators.get(row.creator_user_id),
                }
            )
        return {"items": items}


@router.post("/api/admin/shares")
async def create_share(payload: ShareInput):
    from ...main import StateSession, IndexSession

    async with StateSession() as state, IndexSession() as index:
        created = await create_share_row(state, index, payload)
        await state.commit()
        return share_dict(created.share) | {"code": created.code}


@router.patch("/api/admin/shares/{token}")
async def update_share(token: str, payload: ShareUpdate):
    from ...main import StateSession

    async with StateSession() as session:
        row = await session.get(Share, token)
        if not row:
            raise HTTPException(404, "分享不存在")
        if payload.action == "cancel" or payload.enabled is False:
            await cancel_share_row(session, row)
        elif payload.action == "restore" or payload.enabled is True:
            await restore_share(session, row, payload.duration)
        elif payload.action in {"reset_code", "upgrade"}:
            code = await reset_share_code(session, row)
            await session.commit()
            return share_dict(row) | {"code": code}
        if payload.duration:
            await update_share_duration(session, row, payload.duration)
        await session.commit()
        return share_dict(row)


@router.delete("/api/admin/shares/{token}")
async def delete_share(token: str):
    from ...main import StateSession

    async with StateSession() as session:
        row = await session.get(Share, token)
        if not row:
            raise HTTPException(404, "分享不存在")
        session.add(OperationLog(level="INFO", module="share", action="share_deleted", message=f"删除分享 {token}"))
        await session.delete(row)
        await session.commit()
        return {"ok": True}