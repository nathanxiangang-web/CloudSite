"""FastAPI application composition root.

This module owns application construction and route/plugin registration.
The legacy cloudsite.main module still exposes compatibility symbols during
the 2.0 migration, but it no longer owns the router graph.

Composition is intentionally two-phase:
1. create_app_shell() creates the FastAPI object and core middleware.
2. compose_app(app) imports and registers routers/plugins.

Keeping the phases separate preserves the historical guarantee that
cloudsite.main.app already exists while legacy router modules are imported.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, FastAPI

from .. import __version__
from .exception_handlers import register_exception_handlers
from .lifespan import lifespan
from .middleware import register_middlewares

if TYPE_CHECKING:
    from ..plugins import PluginRegistry


def create_app_shell() -> FastAPI:
    """Create the FastAPI shell before importing legacy router modules."""
    app = FastAPI(title="CloudSite API", version=__version__, lifespan=lifespan)
    register_middlewares(app)
    register_exception_handlers(app)
    return app


def register_public_routers(app: FastAPI) -> APIRouter:
    """Register public/user-facing routers in their historical order."""
    from ..auth import router as auth_router
    from ..site import router as site_router
    from ..userdata import router as userdata_router
    from ..users import router as users_router
    from ..routers.browse import router as browse_router
    from ..routers.catalog import router as catalog_router
    from ..routers.catalog_follow import router as catalog_follow_router
    from ..routers.collections import router as collections_router
    from ..routers.delivery import router as delivery_router
    from ..routers.downloads import router as downloads_router
    from ..routers.health import router as health_router
    from ..routers.home import router as home_router
    from ..routers.notifications import router as notifications_router
    from ..routers.previews import router as previews_router
    from ..routers.quality import router as quality_router
    from ..routers.resources import router as resources_router
    from ..routers.search import router as search_router
    from ..routers.shares import router as shares_router
    from ..routers.sitemap import router as sitemap_router
    from ..routers.submissions import router as submissions_router

    routers = (
        auth_router,
        users_router,
        userdata_router,
        site_router,
        health_router,
        home_router,
        resources_router,
        previews_router,
        search_router,
        collections_router,
        shares_router,
        downloads_router,
        submissions_router,
        notifications_router,
        catalog_router,
        catalog_follow_router,
        sitemap_router,
        browse_router,
        quality_router,
        delivery_router,
    )
    for router in routers:
        app.include_router(router)
    return users_router


def register_admin_routers(app: FastAPI) -> None:
    """Register admin/platform routers in their historical order."""
    from ..platform.tasks.api import router as admin_tasks_router
    from ..routers.admin.alist import router as admin_alist_router
    from ..routers.admin.api_tokens import router as admin_api_tokens_router
    from ..routers.admin.auth import router as admin_auth_router
    from ..routers.admin.automation import router as admin_automation_router
    from ..routers.admin.catalog import router as admin_catalog_router
    from ..routers.admin.catalog_metadata import router as admin_catalog_metadata_router
    from ..routers.admin.collections import router as admin_collections_router
    from ..routers.admin.connections import router as admin_connections_router
    from ..routers.admin.content_roots import router as admin_content_roots_router
    from ..routers.admin.delivery import router as admin_delivery_router
    from ..routers.admin.diagnostics import router as admin_diagnostics_router
    from ..routers.admin.identities import router as admin_identities_router
    from ..routers.admin.index import router as admin_index_router
    from ..routers.admin.metrics import router as admin_metrics_router
    from ..routers.admin.notifications import router as admin_notifications_router
    from ..routers.admin.overview import router as admin_overview_router
    from ..routers.admin.parser_candidates import router as admin_parser_candidates_router
    from ..routers.admin.presentation import router as admin_presentation_router
    from ..routers.admin.publication_scope import router as admin_publication_scope_router
    from ..routers.admin.quality import router as admin_quality_router
    from ..routers.admin.roles import router as admin_roles_router
    from ..routers.admin.search import router as admin_search_router
    from ..routers.admin.setup import router as admin_setup_router
    from ..routers.admin.shares import router as admin_shares_router
    from ..routers.admin.site import router as admin_site_router
    from ..routers.admin.submissions import router as admin_submissions_router
    from ..routers.admin.sync import router as admin_sync_router
    from ..routers.admin.system import router as admin_system_router

    routers = (
        admin_auth_router,
        admin_setup_router,
        admin_overview_router,
        admin_diagnostics_router,
        admin_identities_router,
        admin_alist_router,
        admin_content_roots_router,
        admin_sync_router,
        admin_search_router,
        admin_index_router,
        admin_collections_router,
        admin_shares_router,
        admin_system_router,
        admin_site_router,
        admin_submissions_router,
        admin_notifications_router,
        admin_catalog_router,
        admin_catalog_metadata_router,
        admin_automation_router,
        admin_presentation_router,
        admin_publication_scope_router,
        admin_quality_router,
        admin_metrics_router,
        admin_roles_router,
        admin_delivery_router,
        admin_api_tokens_router,
        admin_connections_router,
        admin_parser_candidates_router,
        admin_tasks_router,
    )
    for router in routers:
        app.include_router(router)


def register_plugin_routers(app: FastAPI) -> "PluginRegistry":
    """Load enabled plugins and register their routers."""
    from ..plugins import PluginRegistry

    registry = PluginRegistry()
    registry.load_enabled()
    for router in registry.get_routers():
        app.include_router(router)
    return registry


def compose_app(app: FastAPI) -> tuple["PluginRegistry", APIRouter]:
    """Apply the route/plugin graph and return transitional compatibility handles."""
    users_router = register_public_routers(app)
    register_admin_routers(app)
    registry = register_plugin_routers(app)
    return registry, users_router
