"""admin/submissions 路由：投稿审核。"""

from fastapi import APIRouter, HTTPException

from ...modules.providers.contracts.public import connection_admin_username
from ...modules.submissions.contracts.public import (
    SubmissionAlreadyPublished,
    SubmissionDeleteForbidden,
    SubmissionIllegalTransition,
    SubmissionNotFound,
    SubmissionResourceInvalid,
    SubmissionResourceOutOfScope,
    SubmissionResourceRequired,
    delete_submission,
    get_admin_submission,
    list_admin_submissions,
    review_submission,
)
from ...schemas import SubmissionReviewInput

router = APIRouter()


@router.get("/api/admin/submissions")
async def admin_submissions(status: str | None = None):
    from ...main import StateSession

    async with StateSession() as state:
        return {
            "items": await list_admin_submissions(
                state,
                status=status,
            )
        }


@router.get("/api/admin/submissions/{submission_id}")
async def admin_submission_detail(submission_id: int):
    from ...main import StateSession

    async with StateSession() as state:
        try:
            return await get_admin_submission(state, submission_id)
        except SubmissionNotFound as exc:
            raise HTTPException(404, "投稿不存在") from exc


@router.patch("/api/admin/submissions/{submission_id}")
async def review_submission_route(
    submission_id: int,
    payload: SubmissionReviewInput,
):
    from ...main import IndexSession, StateSession

    async with StateSession() as state, IndexSession() as index:
        try:
            return await review_submission(
                state,
                index,
                submission_id,
                action=payload.action,
                admin_note=payload.admin_note,
                resource_id=payload.resource_id,
                reviewed_by=await connection_admin_username(state),
            )
        except SubmissionNotFound as exc:
            raise HTTPException(404, "投稿不存在") from exc
        except SubmissionAlreadyPublished as exc:
            raise HTTPException(
                409,
                {
                    "code": "SUBMISSION_ALREADY_PUBLISHED",
                    "message": str(exc),
                },
            ) from exc
        except SubmissionIllegalTransition as exc:
            raise HTTPException(
                409,
                {
                    "code": "SUBMISSION_ILLEGAL_TRANSITION",
                    "message": str(exc),
                },
            ) from exc
        except SubmissionResourceRequired as exc:
            raise HTTPException(
                400,
                {
                    "code": "SUBMISSION_RESOURCE_REQUIRED",
                    "message": str(exc),
                },
            ) from exc
        except SubmissionResourceInvalid as exc:
            raise HTTPException(
                404,
                {
                    "code": "SUBMISSION_RESOURCE_INVALID",
                    "message": str(exc),
                },
            ) from exc
        except SubmissionResourceOutOfScope as exc:
            raise HTTPException(
                404,
                {
                    "code": "SUBMISSION_RESOURCE_OUT_OF_SCOPE",
                    "message": str(exc),
                },
            ) from exc


@router.delete("/api/admin/submissions/{submission_id}")
async def delete_submission_route(submission_id: int):
    from ...main import StateSession

    async with StateSession() as state:
        try:
            await delete_submission(state, submission_id)
        except SubmissionNotFound as exc:
            raise HTTPException(404, "投稿不存在") from exc
        except SubmissionDeleteForbidden as exc:
            raise HTTPException(409, str(exc)) from exc
    return {"ok": True}
