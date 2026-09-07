"""admin/submissions 路由：投稿审核。"""
from fastapi import APIRouter, HTTPException
from sqlalchemy import desc, select

from ...models import AListConnection, Notification, OperationLog, Submission, User, utcnow
from ...schemas import SubmissionReviewInput
from ...services.submissions import submission_dict

router = APIRouter()


@router.get("/api/admin/submissions")
async def admin_submissions(status: str | None = None):
    from ...main import StateSession

    async with StateSession() as state:
        query = select(Submission).order_by(desc(Submission.created_at))
        if status:
            query = query.where(Submission.status == status)
        rows = list((await state.scalars(query)).all())
        user_ids = {row.user_id for row in rows}
        usernames = {u.id: u.username for u in (await state.scalars(select(User).where(User.id.in_(user_ids)))).all()} if user_ids else {}
        return {"items": [submission_dict(row, usernames.get(row.user_id, "")) for row in rows]}


@router.get("/api/admin/submissions/{submission_id}")
async def admin_submission_detail(submission_id: int):
    from ...main import StateSession

    async with StateSession() as state:
        row = await state.get(Submission, submission_id)
        if not row:
            raise HTTPException(404, "投稿不存在")
        user = await state.get(User, row.user_id)
        return submission_dict(row, user.username if user else "")


@router.patch("/api/admin/submissions/{submission_id}")
async def review_submission(submission_id: int, payload: SubmissionReviewInput):
    from ...main import StateSession

    async with StateSession() as state:
        row = await state.get(Submission, submission_id)
        if not row:
            raise HTTPException(404, "投稿不存在")
        action_map = {"approve": "approved", "reject": "rejected", "publish": "published"}
        row.status = action_map[payload.action]
        row.admin_note = payload.admin_note
        row.reviewed_at = utcnow()
        connection = await state.get(AListConnection, 1)
        row.reviewed_by = connection.username if connection else "admin"
        state.add(OperationLog(level="INFO", module="submission", action=f"submission_{payload.action}", message=f"投稿 #{row.id} {row.resource_name} -> {row.status}"))
        notify_title_map = {"approve": "投稿审核通过", "reject": "投稿已被拒绝", "publish": "投稿已发布"}
        notify_level_map = {"approve": "success", "reject": "warning", "publish": "success"}
        notify_body = f"你提交的《{row.resource_name}》已{('通过审核' if payload.action == 'approve' else '被拒绝' if payload.action == 'reject' else '发布')}."
        if payload.admin_note:
            notify_body += f"\n审核备注：{payload.admin_note}"
        state.add(Notification(
            user_id=row.user_id,
            title=notify_title_map[payload.action],
            body=notify_body,
            level=notify_level_map[payload.action],
            source="submission",
        ))
        await state.commit()
        await state.refresh(row)
        user = await state.get(User, row.user_id)
        return submission_dict(row, user.username if user else "")


@router.delete("/api/admin/submissions/{submission_id}")
async def delete_submission(submission_id: int):
    from ...main import StateSession

    async with StateSession() as state:
        row = await state.get(Submission, submission_id)
        if not row:
            raise HTTPException(404, "投稿不存在")
        if row.status != "rejected":
            raise HTTPException(409, "仅已拒绝的投稿可以删除")
        state.add(OperationLog(level="INFO", module="submission", action="submission_deleted", message=f"删除投稿 #{row.id} {row.resource_name}（提交者 user_id={row.user_id}）"))
        await state.delete(row)
        await state.commit()
        return {"ok": True}