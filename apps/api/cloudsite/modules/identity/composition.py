"""Identity module composition helpers."""

from .application.admin_queries import IdentityAdminQueryService
from .infrastructure.admin_query_repository import (
    SqlAlchemyIdentityAdminQueryRepository,
)


def build_identity_admin_query_service() -> IdentityAdminQueryService:
    return IdentityAdminQueryService(SqlAlchemyIdentityAdminQueryRepository())


__all__ = ["build_identity_admin_query_service"]
