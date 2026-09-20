"""Identity admin query application tests."""

from datetime import datetime, timezone

from cloudsite.modules.identity.application.admin_queries import IdentityAdminQueries
from cloudsite.modules.identity.domain.admin_views import (
    IdentityCandidateView,
    IdentityStatsView,
)


NOW = datetime(2026, 9, 1, tzinfo=timezone.utc)


class FakeAdminQueryRepository:
    def __init__(self) -> None:
        self.last_status = None
        self.last_limit = None

    async def stats(self) -> IdentityStatsView:
        return IdentityStatsView(
            total=3,
            legacy_seeded=2,
            random_new=1,
            rename_preserved=4,
            move_preserved=5,
            pending=6,
            ambiguous=7,
            manual_repairs=8,
        )

    async def candidates(self, *, status: str, limit: int):
        self.last_status = status
        self.last_limit = limit
        return [
            IdentityCandidateView(
                id=1,
                cycle_id=2,
                observed_path="/a.zip",
                matched_resource_id="r_one",
                candidate_resource_ids=["r_one", "r_two"],
                match_type="fingerprint",
                confidence=0.5,
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


async def test_admin_queries_delegate_without_http_or_sqlalchemy_concerns():
    repository = FakeAdminQueryRepository()
    queries = IdentityAdminQueries(repository)

    stats = await queries.stats()
    assert stats.to_dict()["random_new"] == 1

    candidates = await queries.candidates(status="open", limit=25)
    assert candidates[0].candidate_resource_ids == ["r_one", "r_two"]
    assert repository.last_status == "open"
    assert repository.last_limit == 25
