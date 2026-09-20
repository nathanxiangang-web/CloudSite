"""Share target/scope orchestration through owner public contracts."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ...collections.contracts.public import (
    CollectionNotFound,
    collection_contains_resource,
    collection_publication_scope,
    get_public_collection,
)
from ...resources.contracts.public import (
    PublicationResourceView,
    folder_publication_target,
    resource_publication_target,
    resource_queries,
)
from ....platform.observability import write_operation_log
from ..domain.code import generate_share_code, hash_share_code
from ..domain.views import CreatedShareView, ShareView
from ..infrastructure.models import Share
from .service import (
    ShareValidationError,
    generate_share_token,
    share_expires_at,
    share_view,
)


async def _target_valid(
    state: AsyncSession,
    index: AsyncSession,
    *,
    object_type: str,
    object_id: str,
) -> bool:
    if object_type == "resource":
        return (
            await resource_publication_target(
                state,
                index,
                object_id,
            )
            is not None
        )
    if object_type == "folder":
        return (
            await folder_publication_target(
                state,
                index,
                object_id,
            )
            is not None
        )
    collection_id = int(object_id) if object_id.isdigit() else -1
    return await collection_publication_scope(
        state,
        index,
        collection_id,
    )


async def target_valid_for_share(
    state: AsyncSession,
    index: AsyncSession,
    share: ShareView,
) -> bool:
    return await _target_valid(
        state,
        index,
        object_type=share.object_type,
        object_id=share.object_id,
    )


async def create_share(
    state: AsyncSession,
    index: AsyncSession,
    *,
    object_type: str,
    object_id: str,
    access_mode: str,
    duration: str,
    title: str = "",
    secret_key: str,
    creator_user_id: int | None = None,
) -> CreatedShareView:
    if access_mode == "direct" and object_type != "resource":
        raise ShareValidationError(
            "SHARE_DIRECT_RESOURCE_ONLY",
            "无分享码直下只支持单文件",
        )
    if not await _target_valid(
        state,
        index,
        object_type=object_type,
        object_id=object_id,
    ):
        raise ShareValidationError(
            "SHARE_TARGET_INVALID",
            "分享对象不存在或不在发布范围内",
        )

    token = generate_share_token()
    while await state.get(Share, token):
        token = generate_share_token()

    code = generate_share_code() if access_mode == "code" else None
    row = Share(
        token=token,
        creator_user_id=creator_user_id,
        object_type=object_type,
        object_id=object_id,
        title=title,
        enabled=True,
        access_mode=access_mode,
        code_hash=(
            hash_share_code(
                token,
                code,
                secret_key=secret_key,
            )
            if code
            else None
        ),
        code_version=1 if code else 0,
        expires_at=share_expires_at(duration),
        access_count=0,
        view_count=0,
        download_count=0,
    )
    state.add(row)
    await write_operation_log(
        state,
        module="share",
        action="share_created",
        message=f"创建分享 {token}",
    )
    await state.flush()
    return CreatedShareView(
        share=share_view(row),
        code=code,
    )


async def build_share_target_payload(
    state: AsyncSession,
    index: AsyncSession,
    share: ShareView,
) -> dict:
    if share.object_type == "resource":
        target = await resource_publication_target(
            state,
            index,
            share.object_id,
        )
        if target is None:
            raise ShareValidationError(
                "SHARE_TARGET_INVALID",
                "分享的资源不存在或不可用",
                status_code=404,
            )
        return target.to_public_dict()

    if share.object_type == "folder":
        target = await folder_publication_target(
            state,
            index,
            share.object_id,
        )
        if target is None:
            raise ShareValidationError(
                "SHARE_TARGET_INVALID",
                "分享的文件夹不存在或不可用",
                status_code=404,
            )
        return target.to_public_dict()

    collection_id = (
        int(share.object_id)
        if share.object_id.isdigit()
        else -1
    )
    if not await collection_publication_scope(
        state,
        index,
        collection_id,
    ):
        raise ShareValidationError(
            "SHARE_TARGET_INVALID",
            "分享的合集不存在或不可用",
            status_code=404,
        )
    try:
        return await get_public_collection(
            state,
            index,
            collection_id,
        )
    except CollectionNotFound as exc:
        raise ShareValidationError(
            "SHARE_TARGET_INVALID",
            "分享的合集不存在或不可用",
            status_code=404,
        ) from exc


async def resolve_share_download_resource(
    state: AsyncSession,
    index: AsyncSession,
    share: ShareView,
    resource_id: str | None,
) -> PublicationResourceView:
    if share.object_type == "resource":
        selected_id = resource_id or share.object_id
        if selected_id != share.object_id:
            raise ShareValidationError(
                "SHARE_RESOURCE_NOT_ALLOWED",
                "资源不属于当前分享",
                status_code=403,
            )
    else:
        if not resource_id:
            raise ShareValidationError(
                "SHARE_RESOURCE_REQUIRED",
                "请选择要下载的资源",
            )
        selected_id = resource_id

    if share.object_type == "folder":
        folder = await folder_publication_target(
            state,
            index,
            share.object_id,
        )
        refs = await resource_queries(index).resource_references(
            resource_ids=[selected_id]
        )
        reference = refs.get(selected_id)
        if (
            folder is None
            or reference is None
            or reference.parent_id != share.object_id
            or reference.root_mapping_id != folder.root_mapping_id
        ):
            raise ShareValidationError(
                "SHARE_RESOURCE_NOT_ALLOWED",
                "资源不属于当前分享",
                status_code=403,
            )
    elif share.object_type != "resource":
        collection_id = (
            int(share.object_id)
            if share.object_id.isdigit()
            else -1
        )
        if not await collection_contains_resource(
            state,
            collection_id,
            selected_id,
        ):
            raise ShareValidationError(
                "SHARE_RESOURCE_NOT_ALLOWED",
                "资源不属于当前分享",
                status_code=403,
            )

    target = await resource_publication_target(
        state,
        index,
        selected_id,
    )
    if target is None:
        raise ShareValidationError(
            "SHARE_TARGET_INVALID",
            "分享资源已不可用",
            status_code=404,
        )
    return target


__all__ = [
    "build_share_target_payload",
    "create_share",
    "resolve_share_download_resource",
    "target_valid_for_share",
]
