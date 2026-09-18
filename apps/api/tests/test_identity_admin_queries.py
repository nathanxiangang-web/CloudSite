"""Identity admin query application tests."""

from datetime import datetime, timezone

from cloudsite.modules.identity.application.admin_queries import IdentityAdminQueryService
from cloudsite.modules.identity.domain.records import IdentityCandidateRecord

NOW = datetime(2026, 9, 1, tzinfo=timezone.utc)


class FakeAdminQueryRepository:
    def __init__(self) -> None:
        self.last_statuses: set[str] | None = None
        self.last_limit: int | None = None

    async def identity_counts(self) -> tuple[int, int]:
        return 7, 3

    async def history_counts(self) -> dict[str, int]:
        return {"rename": 2, "move": 1, "manual_repair": 4}

    async def candidate_status_counts(self) -> dict[str, int]:
        return {"pending": 5, "ambiguous": 6}

    async def list_candidates(
        self,
        statuses: set[str],
        limit: int,
    ) -> list[IdentityCandidateRecord]:
        self.last_statuses = statuses
        self.last_limit = limit
        return [
            IdentityCandidateRecord(
                id=9,
                cycle_id=3,
                observed_path="/software/A.zip",
                matched_resource_id="r_old",
                candidate_resource_ids_json='["r_old","r_other"]',
                match_type="fingerprint",
                confidence=0.75,
                status="ambiguous",
                size=42,
                modified_at=NOW,
                extension="zip",
                mime_type="application/zip",
                fingerprint="fp",
                created_at=NOW,
                resolved_at=None,
            )
        ]


async def test_admin_query_stats_maps_repository_counts():
    service = IdentityAdminQueryService(FakeAdminQueryRepository())
    assert await service.stats() == {
        "total": 7,
        "legacy_seeded": 3,
        "random_new": 4,
        "rename_preserved": 2,
        "move_preserved": 1,
        "pending": 5,
        "ambiguous": 6,
        "manual_repairs": 4,
    }


async def test_admin_query_open_candidates_maps_statuses_and_json():
    repository = FakeAdminQueryRepository()
    service = IdentityAdminQueryService(repository)

    payload = await service.candidates(status="open", limit=25)

    assert repository.last_statuses == {"pending", "ambiguous"}
    assert repository.last_limit == 25
    assert payload["items"][0]["candidate_resource_ids"] == ["r_old", "r_other"]
    assert payload["items"][0]["status"] == "ambiguous"


async def test_admin_query_single_status_passes_one_repository_filter():
    repository = FakeAdminQueryRepository()
    service = IdentityAdminQueryService(repository)

    await service.candidates(status="resolved_move", limit=10)

    assert repository.last_statuses == {"resolved_move"}
    assert repository.last_limit == 10
