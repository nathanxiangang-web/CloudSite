"""submissions 路由：用户投稿。"""
from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import desc, select

from ..auth import require_user, validate_request_origin
from ..models import OperationLog, Submission, utcnow
from ..schemas import SubmissionInput
from ..services.submissions import submission_dict, validate_optional_http_url

router = APIRouter()


@router.post("/api/submissions")
async def create_submission(payload: SubmissionInput, request: Request):
    from ..main import StateSession

    validate_request_origin(request)
    source_url = validate_optional_http_url(payload.source_url, "来源网址")
    download_url = validate_optional_http_url(payload.download_url, "下载链接")
    async with StateSession() as state:
        _, user = await require_user(state, request)
        row = Submission(
            user_id=user.id,
            resource_name=payload.resource_name.strip(),
            resource_type=payload.resource_type,
            description=payload.description.strip(),
            source_url=source_url,
            download_url=download_url,
            copyright_note=payload.copyright_note.strip(),
            note=payload.note.strip(),
            status="pending",
        )
        state.add(row)
        state.add(OperationLog(level="INFO", module="submission", action="submission_created", message=f"用户 {user.username} 提交投稿 {payload.resource_name}"))
        await state.commit()
        await state.refresh(row)
        return submission_dict(row, user.username)


@router.get("/api/submissions/mine")
async def my_submissions(request: Request):
    from ..main import StateSession

    async with StateSession() as state:
        _, user = await require_user(state, request)
        rows = list((await state.scalars(select(Submission).where(Submission.user_id == user.id).order_by(desc(Submission.created_at)))).all())
        await state.commit()
        return {"items": [submission_dict(row, user.username) for row in rows]}
