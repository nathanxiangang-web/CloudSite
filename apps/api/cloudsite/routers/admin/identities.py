"""admin/identities 路由：资源身份统计与候选。"""
import json

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import func, select

from ...infrastructure.security import verify_session_token
from ...models import ResourceIdentity, ResourceIdentityCandidate, ResourceIdentityHistory

router = APIRouter()

SESSION_COOKIE = "cloudsite_session"


def require_explicit_admin(request: Request) -> None:
    if not verify_session_token(request.cookies.get(SESSION_COOKIE)):
        raise HTTPException(
            status_code=403,
            detail={"code": "ADMIN_REQUIRED", "message": "请先登录管理后台"},
        )


@router.get("/api/admin/identities/stats")
async def identity_stats(request: Request):
    from ...main import StateSession, IndexSession

    require_explicit_admin(request)
    async with StateSession() as state:
        total = int(await state.scalar(select(func.count()).select_from(ResourceIdentity)) or 0)
        legacy = int(
            await state.scalar(
                select(func.count())
                .select_from(ResourceIdentity)
                .where(ResourceIdentity.created_from == "legacy_migration")
            )
            or 0
        )
        history_rows = (
            await state.execute(
                select(ResourceIdentityHistory.event_type, func.count())
                .group_by(ResourceIdentityHistory.event_type)
            )
        ).all()
    history = {event_type: int(count) for event_type, count in history_rows}
    async with IndexSession() as index:
        candidate_rows = (
            await index.execute(
                select(ResourceIdentityCandidate.status, func.count())
                .group_by(ResourceIdentityCandidate.status)
            )
        ).all()
    candidates = {status: int(count) for status, count in candidate_rows}
    return {
        "total": total,
        "legacy_seeded": legacy,
        "random_new": total - legacy,
        "rename_preserved": history.get("rename", 0),
        "move_preserved": history.get("move", 0),
        "pending": candidates.get("pending", 0),
        "ambiguous": candidates.get("ambiguous", 0),
        "manual_repairs": history.get("manual_repair", 0),
    }


@router.get("/api/admin/identities/candidates")
async def identity_candidates(
    request: Request,
    status: str = Query("open", pattern="^(open|pending|ambiguous|resolved_move|resolved_new|cancelled)$"),
    limit: int = Query(50, ge=1, le=200),
):
    from ...main import IndexSession

    require_explicit_admin(request)
    statement = select(ResourceIdentityCandidate).order_by(ResourceIdentityCandidate.id.desc()).limit(limit)
    if status == "open":
        statement = statement.where(ResourceIdentityCandidate.status.in_(("pending", "ambiguous")))
    else:
        statement = statement.where(ResourceIdentityCandidate.status == status)
    async with IndexSession() as index:
        rows = list((await index.scalars(statement)).all())
    return {
        "items": [
            {
                "id": row.id,
                "cycle_id": row.cycle_id,
                "observed_path": row.observed_path,
                "matched_resource_id": row.matched_resource_id,
                "candidate_resource_ids": json.loads(row.candidate_resource_ids_json or "[]"),
                "match_type": row.match_type,
                "confidence": row.confidence,
                "status": row.status,
                "size": row.size,
                "modified_at": row.modified_at,
                "extension": row.extension,
                "mime_type": row.mime_type,
                "fingerprint": row.fingerprint,
                "created_at": row.created_at,
                "resolved_at": row.resolved_at,
            }
            for row in rows
        ]
    }