"""submissions 路由：用户投稿。"""

from fastapi import APIRouter, HTTPException, Request

from ..auth import require_user, validate_request_origin
from ..modules.submissions.contracts.public import (
    SubmissionValidationError,
    create_submission,
    list_user_submissions,
)
from ..schemas import SubmissionInput

router = APIRouter()


@router.post("/api/submissions")
async def create_submission_route(
    payload: SubmissionInput,
    request: Request,
):
    from ..main import StateSession

    validate_request_origin(request)
    async with StateSession() as state:
        _, user = await require_user(state, request)
        try:
            return await create_submission(
                state,
                user_id=user.id,
                username=user.username,
                values=payload.model_dump(),
            )
        except SubmissionValidationError as exc:
            raise HTTPException(400, str(exc)) from exc


@router.get("/api/submissions/mine")
async def my_submissions(request: Request):
    from ..main import StateSession

    async with StateSession() as state:
        _, user = await require_user(state, request)
        return {
            "items": await list_user_submissions(
                state,
                user_id=user.id,
                username=user.username,
            )
        }
