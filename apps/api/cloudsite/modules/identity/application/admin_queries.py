"""Admin-facing Identity query application service."""

from __future__ import annotations

import json

from .ports import IdentityAdminQueryRepository


class IdentityAdminQueryService:
    def __init__(self, repository: IdentityAdminQueryRepository) -> None:
        self._repository = repository

    async def stats(self) -> dict[str, int]:
        total, legacy = await self._repository.identity_counts()
        history = await self._repository.history_counts()
        candidates = await self._repository.candidate_status_counts()
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

    async def candidates(self, *, status: str, limit: int) -> dict[str, list[dict]]:
        statuses = {"pending", "ambiguous"} if status == "open" else {status}
        rows = await self._repository.list_candidates(statuses, limit)
        return {
            "items": [
                {
                    "id": row.id,
                    "cycle_id": row.cycle_id,
                    "observed_path": row.observed_path,
                    "matched_resource_id": row.matched_resource_id,
                    "candidate_resource_ids": json.loads(
                        row.candidate_resource_ids_json or "[]"
                    ),
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


__all__ = ["IdentityAdminQueryService"]
