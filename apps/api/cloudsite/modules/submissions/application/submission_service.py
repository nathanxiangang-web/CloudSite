"""Submissions application service and lifecycle boundary."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....platform.observability import write_operation_log
from ...notifications.contracts.public import create_user_notification
from ...providers.contracts.public import enabled_root_ids
from ...resources.contracts.public import resource_queries
from ...users.contracts.public import user_references
from ..infrastructure.models import Submission, utcnow


class SubmissionError(Exception):
    pass


class SubmissionValidationError(SubmissionError):
    pass


class SubmissionNotFound(SubmissionError):
    def __init__(self, submission_id: int):
        super().__init__(f"submission not found: {submission_id}")
        self.submission_id = submission_id


class SubmissionIllegalTransition(SubmissionError):
    pass


class SubmissionAlreadyPublished(SubmissionError):
    pass


class SubmissionResourceRequired(SubmissionError):
    pass


class SubmissionResourceInvalid(SubmissionError):
    pass


class SubmissionResourceOutOfScope(SubmissionError):
    pass


class SubmissionDeleteForbidden(SubmissionError):
    pass


def submission_dict(row: Submission, username: str) -> dict[str, Any]:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "username": username,
        "resource_name": row.resource_name,
        "resource_type": row.resource_type,
        "description": row.description,
        "source_url": row.source_url,
        "download_url": row.download_url,
        "copyright_note": row.copyright_note,
        "note": row.note,
        "status": row.status,
        "admin_note": row.admin_note,
        "reviewed_by": row.reviewed_by,
        "reviewed_at": row.reviewed_at,
        "published_resource_id": row.published_resource_id,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def validate_optional_http_url(value: str, field_name: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise SubmissionValidationError(
            f"{field_name} 必须是 http 或 https 链接"
        )
    return value


async def create_submission(
    state: AsyncSession,
    *,
    user_id: int,
    username: str,
    values: dict[str, Any],
) -> dict[str, Any]:
    source_url = validate_optional_http_url(
        str(values.get("source_url") or ""),
        "来源网址",
    )
    download_url = validate_optional_http_url(
        str(values.get("download_url") or ""),
        "下载链接",
    )
    resource_name = str(values.get("resource_name") or "").strip()
    row = Submission(
        user_id=user_id,
        resource_name=resource_name,
        resource_type=str(values.get("resource_type") or ""),
        description=str(values.get("description") or "").strip(),
        source_url=source_url,
        download_url=download_url,
        copyright_note=str(values.get("copyright_note") or "").strip(),
        note=str(values.get("note") or "").strip(),
        status="pending",
    )
    state.add(row)
    await write_operation_log(
        state,
        level="INFO",
        module="submission",
        action="submission_created",
        message=f"用户 {username} 提交投稿 {resource_name}",
    )
    await state.commit()
    await state.refresh(row)
    return submission_dict(row, username)


async def list_user_submissions(
    state: AsyncSession,
    *,
    user_id: int,
    username: str,
) -> list[dict[str, Any]]:
    rows = list(
        (
            await state.scalars(
                select(Submission)
                .where(Submission.user_id == user_id)
                .order_by(desc(Submission.created_at))
            )
        ).all()
    )
    return [submission_dict(row, username) for row in rows]


async def list_admin_submissions(
    state: AsyncSession,
    *,
    status: str | None = None,
) -> list[dict[str, Any]]:
    stmt = select(Submission).order_by(desc(Submission.created_at))
    if status:
        stmt = stmt.where(Submission.status == status)
    rows = list((await state.scalars(stmt)).all())
    refs = await user_references(
        state,
        user_ids=[row.user_id for row in rows],
    )
    return [
        submission_dict(
            row,
            refs[row.user_id].username if row.user_id in refs else "",
        )
        for row in rows
    ]


async def get_admin_submission(
    state: AsyncSession,
    submission_id: int,
) -> dict[str, Any]:
    row = await state.get(Submission, submission_id)
    if row is None:
        raise SubmissionNotFound(submission_id)
    refs = await user_references(state, user_ids=[row.user_id])
    return submission_dict(
        row,
        refs[row.user_id].username if row.user_id in refs else "",
    )


async def review_submission(
    state: AsyncSession,
    index: AsyncSession,
    submission_id: int,
    *,
    action: str,
    admin_note: str,
    resource_id: str | None,
    reviewed_by: str,
) -> dict[str, Any]:
    row = await state.get(Submission, submission_id)
    if row is None:
        raise SubmissionNotFound(submission_id)

    current_status = row.status
    if action in ("approve", "reject"):
        if current_status != "pending":
            raise SubmissionIllegalTransition(
                "仅待审核投稿可执行此操作"
            )
    elif action == "publish":
        if current_status not in ("approved", "published"):
            raise SubmissionIllegalTransition(
                "仅已通过审核的投稿可发布"
            )
        if not resource_id:
            raise SubmissionResourceRequired("发布需要指定资源 ID")
        if current_status == "published":
            if row.published_resource_id == resource_id:
                refs = await user_references(
                    state,
                    user_ids=[row.user_id],
                )
                return submission_dict(
                    row,
                    refs[row.user_id].username
                    if row.user_id in refs
                    else "",
                )
            raise SubmissionAlreadyPublished("投稿已绑定其他资源")

        resource = await resource_queries(index).catalog_resource(
            resource_id=resource_id
        )
        if resource is None or resource.status != "active":
            raise SubmissionResourceInvalid("资源不存在或已不可用")
        roots = await enabled_root_ids(state)
        if (
            resource.root_mapping_id is None
            or resource.root_mapping_id not in roots
        ):
            raise SubmissionResourceOutOfScope("资源不在当前发布范围内")
        row.published_resource_id = resource_id
    else:
        raise SubmissionIllegalTransition(f"未知审核动作：{action}")

    action_map = {
        "approve": "approved",
        "reject": "rejected",
        "publish": "published",
    }
    row.status = action_map[action]
    row.admin_note = admin_note
    row.reviewed_at = utcnow()
    row.reviewed_by = reviewed_by

    await write_operation_log(
        state,
        level="INFO",
        module="submission",
        action=f"submission_{action}",
        message=f"投稿 #{row.id} {row.resource_name} -> {row.status}",
    )

    title_map = {
        "approve": "投稿审核通过",
        "reject": "投稿已被拒绝",
        "publish": "投稿已发布",
    }
    level_map = {
        "approve": "success",
        "reject": "warning",
        "publish": "success",
    }
    outcome = (
        "通过审核"
        if action == "approve"
        else "被拒绝"
        if action == "reject"
        else "发布"
    )
    body = f"你提交的《{row.resource_name}》已{outcome}."
    if admin_note:
        body += f"\n审核备注：{admin_note}"
    await create_user_notification(
        state,
        user_id=row.user_id,
        title=title_map[action],
        body=body,
        level=level_map[action],
        source="submission",
    )

    await state.commit()
    await state.refresh(row)
    refs = await user_references(state, user_ids=[row.user_id])
    return submission_dict(
        row,
        refs[row.user_id].username if row.user_id in refs else "",
    )


async def delete_submission(
    state: AsyncSession,
    submission_id: int,
) -> None:
    row = await state.get(Submission, submission_id)
    if row is None:
        raise SubmissionNotFound(submission_id)
    if row.status != "rejected":
        raise SubmissionDeleteForbidden(
            "仅已拒绝的投稿可以删除"
        )
    await write_operation_log(
        state,
        level="INFO",
        module="submission",
        action="submission_deleted",
        message=(
            f"删除投稿 #{row.id} {row.resource_name}"
            f"（提交者 user_id={row.user_id}）"
        ),
    )
    await state.delete(row)
    await state.commit()


__all__ = [
    "SubmissionError",
    "SubmissionValidationError",
    "SubmissionNotFound",
    "SubmissionIllegalTransition",
    "SubmissionAlreadyPublished",
    "SubmissionResourceRequired",
    "SubmissionResourceInvalid",
    "SubmissionResourceOutOfScope",
    "SubmissionDeleteForbidden",
    "submission_dict",
    "validate_optional_http_url",
    "create_submission",
    "list_user_submissions",
    "list_admin_submissions",
    "get_admin_submission",
    "review_submission",
    "delete_submission",
]
