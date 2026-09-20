"""A4 user-facing content feedback route.

 Logged-in users can submit feedback about content issues (broken links,
 wrong info, missing content). The feedback auto-creates a QualityTodo.
"""
from fastapi import APIRouter, HTTPException, Request

from ..auth import require_user, validate_request_origin
from ..quality_schemas import ContentFeedbackInput, ContentFeedbackSummary

router = APIRouter()


def _quality_service():
    from ..services import quality  # noqa: PLC0415

    return quality


@router.post("/api/me/quality/feedback", response_model=ContentFeedbackSummary, status_code=201)
async def submit_feedback(body: ContentFeedbackInput, request: Request):
    validate_request_origin(request)
    from ..main import StateSession

    async with StateSession() as state:
        _, user = await require_user(state, request)
        service = _quality_service()
        summary = await service.create_content_feedback(
            state,
            user_id=user.id,
            target_type=body.target_type,
            target_id=body.target_id,
            feedback_kind=body.feedback_kind,
            description=body.description,
        )
        await state.commit()
        return ContentFeedbackSummary(
            feedback_id=summary.feedback_id,
            user_id=summary.user_id,
            target_type=summary.target_type,
            target_id=summary.target_id,
            feedback_kind=summary.feedback_kind,
            description=summary.description,
            status=summary.status,
            admin_note=summary.admin_note,
            reviewed_by=summary.reviewed_by,
            reviewed_at=summary.reviewed_at,
            todo_id=summary.todo_id,
            created_at=summary.created_at,
            updated_at=summary.updated_at,
        )