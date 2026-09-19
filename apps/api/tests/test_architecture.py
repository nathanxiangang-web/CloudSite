"""Architecture dependency tests for CloudSite 2.0 Modular Monolith.

Enforces the dependency rules defined in docs/development/dependency-rules.md:

1. Modules import contracts only (no cross-module internal imports)
2. No module may import from cloudsite.main
3. Platform cannot depend on modules
4. No new top-level .py files in cloudsite/ (excluding legacy allowlist)

These tests are forward-looking: they validate the module structure as code
migrates from the flat 1.x layout to the 2.0 modular layout.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CLOUDSITE = ROOT / "cloudsite"
MODULES = CLOUDSITE / "modules"
PLATFORM = CLOUDSITE / "platform"

LEGACY_TOP_LEVEL_FILES = {
    "__init__.py",
    "main.py",
    "worker_main.py",
    "config.py",
    "database.py",
    "models.py",
    "migrations.py",
    "indexer.py",
    "schemas.py",
    "sessions.py",
    "auth.py",
    "users.py",
    "userdata.py",
    "site.py",
    "site_assets.py",
    "admin_auth.py",
    "alist.py",
    "search.py",
    "preview.py",
    "download.py",
    "download_rate_limit.py",
    "office.py",
    "crypto.py",
    "request_context.py",
    "api_schemas.py",
    "automation_schemas.py",
    "catalog_metadata_schemas.py",
    "catalog_schemas.py",
    "connection_schemas.py",
    "delivery_schemas.py",
    "metrics_schemas.py",
    "parser_candidate_schemas.py",
    "quality_schemas.py",
    "role_schemas.py",
}


def _extract_imports(source: str) -> list[str]:
    """Extract all import module paths from Python source code."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
    return imports


def _python_files(directory: Path) -> list[Path]:
    """Yield all .py files under a directory (excluding __init__.py)."""
    if not directory.exists():
        return []
    return [p for p in directory.rglob("*.py") if p.name != "__init__.py"]


def _module_name(file_path: Path) -> str | None:
    """Extract the module name from a path under modules/."""
    try:
        rel = file_path.relative_to(MODULES)
        return rel.parts[0]
    except (ValueError, IndexError):
        return None


class TestModuleBoundaryImports:
    """Rule 1: Modules import contracts only."""

    def test_modules_do_not_import_other_module_internals(self):
        violations: list[str] = []
        for py_file in _python_files(MODULES):
            source = py_file.read_text(encoding="utf-8")
            current_module = _module_name(py_file)
            for imp in _extract_imports(source):
                match = re.match(r"cloudsite\.modules\.(\w+)\.", imp)
                if match and match.group(1) != current_module:
                    if ".contracts." not in imp:
                        violations.append(
                            f"{py_file.relative_to(ROOT)}: "
                            f"imports '{imp}' from module '{match.group(1)}' "
                            f"(only contracts.* allowed)"
                        )
        assert not violations, "Cross-module internal imports:\n" + "\n".join(violations)


class TestNoMainDependency:
    """Rule 3: No module may import from cloudsite.main."""

    def test_modules_do_not_import_main(self):
        violations: list[str] = []
        for py_file in _python_files(MODULES):
            source = py_file.read_text(encoding="utf-8")
            for imp in _extract_imports(source):
                if imp == "cloudsite.main" or imp.startswith("cloudsite.main."):
                    violations.append(
                        f"{py_file.relative_to(ROOT)}: imports '{imp}'"
                    )
        assert not violations, "Modules importing cloudsite.main:\n" + "\n".join(violations)

    def test_platform_does_not_import_main(self):
        violations: list[str] = []
        for py_file in _python_files(PLATFORM):
            source = py_file.read_text(encoding="utf-8")
            for imp in _extract_imports(source):
                if imp == "cloudsite.main" or imp.startswith("cloudsite.main."):
                    violations.append(
                        f"{py_file.relative_to(ROOT)}: imports '{imp}'"
                    )
        assert not violations, "Platform importing cloudsite.main:\n" + "\n".join(violations)


class TestPlatformIsolation:
    """Rule 4: Platform cannot depend on modules."""

    def test_platform_does_not_import_modules(self):
        violations: list[str] = []
        for py_file in _python_files(PLATFORM):
            source = py_file.read_text(encoding="utf-8")
            for imp in _extract_imports(source):
                if imp.startswith("cloudsite.modules."):
                    violations.append(
                        f"{py_file.relative_to(ROOT)}: imports '{imp}'"
                    )
        assert not violations, "Platform importing from modules:\n" + "\n".join(violations)


class TestNoNewTopLevelFiles:
    """Rule 6: No new top-level .py files in cloudsite/."""

    def test_no_new_top_level_python_files(self):
        if not CLOUDSITE.exists():
            return
        top_level = {
            p.name for p in CLOUDSITE.iterdir() if p.is_file() and p.suffix == ".py"
        }
        new_files = top_level - LEGACY_TOP_LEVEL_FILES
        assert not new_files, (
            f"New top-level .py files in cloudsite/ (must go to modules/ or platform/):\n"
            + "\n".join(sorted(new_files))
        )


class TestCompositionRoot:
    """Application wiring belongs in infrastructure/composition.py, not main.py."""

    def test_main_does_not_register_routers_directly(self):
        main_file = CLOUDSITE / "main.py"
        source = main_file.read_text(encoding="utf-8")
        tree = ast.parse(source)

        assert ".include_router(" not in source
        assert "create_app_shell()" in source
        assert "compose_app(app)" in source

        router_alias_imports: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            for alias in node.names:
                if alias.name == "router":
                    router_alias_imports.append(
                        f"line {node.lineno}: from {node.module or '<relative>'} import router"
                    )
        assert not router_alias_imports, (
            "cloudsite.main must not own router imports:\n" + "\n".join(router_alias_imports)
        )

    def test_composition_root_owns_router_registration(self):
        composition = CLOUDSITE / "infrastructure" / "composition.py"
        assert composition.exists()
        source = composition.read_text(encoding="utf-8")
        assert "def create_app_shell(" in source
        assert "def compose_app(" in source
        assert "app.include_router(" in source


class TestIdentityAdminRouterBoundary:
    """Identity admin HTTP routes must not own persistence queries."""

    def test_identity_admin_router_has_no_orm_or_main_dependency(self):
        router_file = CLOUDSITE / "routers" / "admin" / "identities.py"
        source = router_file.read_text(encoding="utf-8")

        assert "sqlalchemy" not in source
        assert "from ...models" not in source
        assert "from ...main" not in source
        assert "identity_stats_payload" in source
        assert "identity_candidates_payload" in source


class TestIndexingResourcePersistenceBoundary:
    """Indexing may consume Resources contracts but must not own resource ORM."""

    def test_production_store_has_no_resource_orm_or_sqlalchemy_dependency(self):
        store_file = (
            CLOUDSITE
            / "modules"
            / "indexing"
            / "infrastructure"
            / "production_store.py"
        )
        source = store_file.read_text(encoding="utf-8")

        assert "cloudsite.models" not in source
        assert "sqlalchemy" not in source
        assert "modules.resources.infrastructure" not in source
        assert "modules.resources.contracts" in source



class TestResourcesRouterSqlBoundary:
    """Resources router no longer owns ORM/query construction."""

    def test_resources_router_has_no_orm_dependency(self):
        router_file = CLOUDSITE / "routers" / "resources.py"
        source = router_file.read_text(encoding="utf-8")

        assert "sqlalchemy" not in source
        assert "from ..models" not in source
        assert "cloudsite.models" not in source
        assert "select(" not in source
        assert "session.get(" not in source
        assert "session.scalar(" not in source
        assert "session.scalars(" not in source


class TestPreviewProviderBoundary:
    """Resources-owned preview helpers may not own provider credentials or clients."""

    def test_preview_helpers_use_providers_contract_only(self):
        helper_files = (
            CLOUDSITE / "modules" / "resources" / "infrastructure" / "preview.py",
            CLOUDSITE
            / "modules"
            / "resources"
            / "infrastructure"
            / "office_preview.py",
        )
        for helper_file in helper_files:
            source = helper_file.read_text(encoding="utf-8")
            assert "AListClient" not in source
            assert "decrypt_secret" not in source
            assert "modules.providers.contracts" in source


class TestDeliveryPackageInitialization:
    """Delivery package import must not eagerly load its public contract."""

    def test_delivery_package_init_is_side_effect_free(self):
        init_file = CLOUDSITE / "modules" / "delivery" / "__init__.py"
        source = init_file.read_text(encoding="utf-8")
        tree = ast.parse(source)

        imports = [
            node
            for node in tree.body
            if isinstance(node, (ast.Import, ast.ImportFrom))
        ]
        assert imports == []


class TestAutomationParserCoreBoundary:
    """Automation parser core uses owned code and public module contracts."""

    def test_parser_application_has_no_shared_core_imports(self):
        paths = [
            CLOUDSITE
            / "modules"
            / "automation"
            / "application"
            / "parser_candidate_batch.py",
            CLOUDSITE
            / "modules"
            / "automation"
            / "application"
            / "parser_candidate_runner.py",
            CLOUDSITE
            / "modules"
            / "automation"
            / "application"
            / "parser_candidate_seeding.py",
            CLOUDSITE
            / "modules"
            / "automation"
            / "application"
            / "parser_candidates.py",
            CLOUDSITE
            / "modules"
            / "automation"
            / "application"
            / "parser_evaluation.py",
        ]
        for path in paths:
            source = path.read_text(encoding="utf-8")
            assert "cloudsite.models" not in source
            assert "from ....models" not in source
            assert "cloudsite.services" not in source
            assert "from ....services" not in source

    def test_parser_resource_reads_use_resources_contract(self):
        for relative in (
            "parser_candidate_batch.py",
            "parser_candidate_runner.py",
            "parser_candidate_seeding.py",
        ):
            path = (
                CLOUDSITE
                / "modules"
                / "automation"
                / "application"
                / relative
            )
            source = path.read_text(encoding="utf-8")
            assert "resources.contracts.public" in source
            assert "index.get(Resource" not in source

    def test_parser_seeding_uses_indexing_contract(self):
        path = (
            CLOUDSITE
            / "modules"
            / "automation"
            / "application"
            / "parser_candidate_seeding.py"
        )
        source = path.read_text(encoding="utf-8")
        assert "indexing.contracts.public" in source
        assert "parser_seed_run(" in source
        assert "parser_seed_changes(" in source
        assert "from ....models" not in source

    def test_parser_domain_and_orm_are_automation_owned(self):
        parser_file = (
            CLOUDSITE
            / "modules"
            / "automation"
            / "domain"
            / "resource_name_parser.py"
        )
        model_file = (
            CLOUDSITE
            / "modules"
            / "automation"
            / "infrastructure"
            / "models.py"
        )
        parser_source = parser_file.read_text(encoding="utf-8")
        model_source = model_file.read_text(encoding="utf-8")

        assert "cloudsite.services" not in parser_source
        assert "cloudsite.models" not in model_source
        assert "class ParserCandidateTask(" in model_source
        assert "platform.db" in model_source

    def test_legacy_parser_service_is_implementation_free_facade(self):
        path = CLOUDSITE / "services" / "resource_name_parser.py"
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        assert "modules.automation.domain.resource_name_parser" in source
        implementations = [
            node
            for node in tree.body
            if isinstance(
                node,
                (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
            )
        ]
        assert implementations == []


class TestCatalogModuleCoreBoundary:
    """Catalog core application depends on module models and public contracts."""

    def test_catalog_application_has_no_shared_core_imports(self):
        paths = [
            CLOUDSITE / "modules" / "catalog" / "application" / "catalog_entry.py",
            CLOUDSITE / "modules" / "catalog" / "application" / "catalog_release.py",
        ]
        for path in paths:
            source = path.read_text(encoding="utf-8")
            assert "cloudsite.models" not in source
            assert "from ....models" not in source
            assert "cloudsite.services" not in source
            assert "from ....services" not in source
            assert "index.get(Resource" not in source
            assert "providers.contracts.public" in source
            assert "resources.contracts.public" in source
            assert "from ..infrastructure.models import" in source

    def test_catalog_release_notifications_use_notifications_contract(self):
        path = (
            CLOUDSITE
            / "modules"
            / "catalog"
            / "application"
            / "release_notifications.py"
        )
        source = path.read_text(encoding="utf-8")
        assert "notifications.contracts.public" in source
        assert "cloudsite.models" not in source
        assert "from ...notifications.infrastructure" not in source

    def test_catalog_orm_is_module_owned(self):
        path = CLOUDSITE / "modules" / "catalog" / "infrastructure" / "models.py"
        source = path.read_text(encoding="utf-8")
        imports = _extract_imports(source)

        assert "cloudsite.models" not in imports
        assert "models" not in imports
        assert "platform.db" in source


class TestNotificationsModuleBoundary:
    """Notifications owns notification persistence and router ORM work."""

    def test_notification_application_has_no_shared_core_imports(self):
        path = (
            CLOUDSITE
            / "modules"
            / "notifications"
            / "application"
            / "notification_service.py"
        )
        source = path.read_text(encoding="utf-8")

        assert "cloudsite.models" not in source
        assert "from ....models" not in source
        assert "cloudsite.services" not in source
        assert "from ....services" not in source
        assert "notifications.infrastructure.models" not in source
        assert "from ..infrastructure.models import Notification" in source

    def test_notification_routers_are_orm_free(self):
        paths = [
            CLOUDSITE / "routers" / "notifications.py",
            CLOUDSITE / "routers" / "admin" / "notifications.py",
        ]
        for path in paths:
            source = path.read_text(encoding="utf-8")
            assert "sqlalchemy" not in source
            assert "cloudsite.models" not in source
            assert "from ..models" not in source
            assert "from ...models" not in source
            assert "services.notifications" not in source
            assert "modules.notifications.contracts.public" in source


class TestIndexingSharedCoreBoundary:
    """Indexing runtime code may not depend on shared ORM/session modules."""

    def test_alist_adapter_uses_structural_root_type(self):
        path = (
            CLOUDSITE
            / "modules"
            / "indexing"
            / "infrastructure"
            / "alist_adapter.py"
        )
        source = path.read_text(encoding="utf-8")

        assert "cloudsite.models" not in source
        assert "ContentRootView(Protocol)" in source

    def test_legacy_bridge_uses_platform_db_not_shared_database_or_models(self):
        path = (
            CLOUDSITE
            / "modules"
            / "indexing"
            / "infrastructure"
            / "legacy_bridge.py"
        )
        source = path.read_text(encoding="utf-8")

        assert "cloudsite.database" not in source
        assert "cloudsite.models" not in source
        assert "cloudsite.platform.db" in source

    def test_startup_sync_uses_zero_argument_compatibility_entry(self):
        path = CLOUDSITE / "tasks" / "sync.py"
        source = path.read_text(encoding="utf-8")

        assert "await run_indexing_v2_production(store_factory=" not in source
        assert "await run_indexing_v2_production()" in source


class TestRateLimitOwnershipBoundary:
    """Download rate limiting is Resources-owned, not Delivery-owned."""

    def test_resources_rate_limit_has_no_legacy_database_or_shared_model_imports(self):
        path = (
            CLOUDSITE
            / "modules"
            / "resources"
            / "infrastructure"
            / "rate_limit.py"
        )
        source = path.read_text(encoding="utf-8")

        assert "cloudsite.database" not in source
        assert "from ....database" not in source
        assert "cloudsite.models" not in source
        assert "from ....models" not in source
        assert "platform.db" in source
        assert "from .models import DownloadRateLimit" in source

    def test_delivery_rate_limit_is_resources_contract_facade(self):
        path = (
            CLOUDSITE
            / "modules"
            / "delivery"
            / "infrastructure"
            / "rate_limit.py"
        )
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        assert "modules.resources.contracts" in source
        assert "cloudsite.database" not in source
        assert "cloudsite.models" not in source
        implementations = [
            node
            for node in tree.body
            if isinstance(
                node,
                (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
            )
        ]
        assert implementations == []


class TestDeliveryOrmBoundary:
    """Delivery application code may not depend on shared ORM."""

    def test_download_event_uses_delivery_owned_model(self):
        event_file = (
            CLOUDSITE
            / "modules"
            / "delivery"
            / "application"
            / "download_event.py"
        )
        source = event_file.read_text(encoding="utf-8")

        assert "cloudsite.models" not in source
        assert "from ....models" not in source
        assert "from ..infrastructure.models import DownloadEvent" in source


class TestDownloadRuntimeBoundary:
    """Download HTTP/provider boundaries must remain module-owned."""

    def test_download_router_has_no_orm_or_legacy_connection_dependency(self):
        router_file = CLOUDSITE / "routers" / "downloads.py"
        source = router_file.read_text(encoding="utf-8")

        assert "from ..models" not in source
        assert "cloudsite.models" not in source
        assert "sqlalchemy" not in source
        assert "index.get(" not in source
        assert "resolve_resource_connection" not in source
        assert "resource_in_publication_scope" not in source
        assert "resource_queries(" in source
        assert "provider_runtime(" in source

    def test_delivery_download_uses_providers_contract_only(self):
        domain_file = (
            CLOUDSITE
            / "modules"
            / "delivery"
            / "domain"
            / "download.py"
        )
        source = domain_file.read_text(encoding="utf-8")

        assert "AListClient" not in source
        assert "AListError" not in source
        assert "decrypt_secret" not in source
        assert "cloudsite.alist" not in source
        assert "cloudsite.crypto" not in source
        assert "modules.providers.contracts" in source


class TestPreviewCompatibilityFacades:
    """Legacy top-level preview modules must remain implementation-free facades."""

    def test_preview_and_office_are_thin_facades(self):
        for relative in ("preview.py", "office.py"):
            path = CLOUDSITE / relative
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)

            assert "modules.resources.infrastructure" in source
            implementations = [
                node
                for node in tree.body
                if isinstance(
                    node,
                    (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
                )
            ]
            assert implementations == []


class TestPreviewRouterBoundary:
    """Preview router delegates resource lookup and provider access."""

    def test_preview_router_has_no_orm_or_legacy_connection_dependency(self):
        router_file = CLOUDSITE / "routers" / "previews.py"
        source = router_file.read_text(encoding="utf-8")

        assert "cloudsite.models" not in source
        assert "from ..models" not in source
        assert "sqlalchemy" not in source
        assert "session.get(" not in source
        assert "index.get(" not in source
        assert "resolve_resource_connection" not in source
        assert "resource_in_publication_scope" not in source
        assert "resource_queries(" in source
        assert "provider_runtime(" in source


class TestResourcesListRouterBoundary:
    """Migrated list routes delegate SQL ownership to Resources."""

    def test_resource_and_folder_list_handlers_delegate_to_resources_queries(self):
        router_file = CLOUDSITE / "routers" / "resources.py"
        tree = ast.parse(router_file.read_text(encoding="utf-8"))

        functions = {
            node.name: ast.get_source_segment(
                router_file.read_text(encoding="utf-8"),
                node,
            )
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

        for name in ("resources", "folders"):
            source = functions[name] or ""
            assert "resource_queries(session)" in source
            assert "select(" not in source
            assert "session.scalars(" not in source
            assert "session.scalar(" not in source



class TestModuleStructure:
    """Validate that each module has the required minimum structure."""

    REQUIRED_DIRS = {"api", "application", "infrastructure", "contracts", "tests"}


    def test_modules_have_required_directories(self):
        if not MODULES.exists():
            return
        violations: list[str] = []
        for mod_dir in sorted(MODULES.iterdir()):
            if not mod_dir.is_dir() or mod_dir.name.startswith("_"):
                continue
            existing = {d.name for d in mod_dir.iterdir() if d.is_dir()}
            missing = self.REQUIRED_DIRS - existing
            if missing:
                violations.append(
                    f"modules/{mod_dir.name}/ missing: {sorted(missing)}"
                )
        assert not violations, "Missing required directories:\n" + "\n".join(violations)

    def test_modules_have_manifest(self):
        if not MODULES.exists():
            return
        violations: list[str] = []
        for mod_dir in sorted(MODULES.iterdir()):
            if not mod_dir.is_dir() or mod_dir.name.startswith("_"):
                continue
            manifest = mod_dir / "module.yaml"
            if not manifest.exists():
                violations.append(f"modules/{mod_dir.name}/module.yaml (missing)")
                continue
            content = manifest.read_text(encoding="utf-8")
            if "schema_version: 1" not in content:
                violations.append(f"modules/{mod_dir.name}/module.yaml (schema_version != 1)")
            if f'name: "{mod_dir.name}"' not in content:
                violations.append(f"modules/{mod_dir.name}/module.yaml (name mismatch)")
        assert not violations, "Invalid module manifests:\n" + "\n".join(violations)


    def test_modules_have_readme(self):
        if not MODULES.exists():
            return
        violations: list[str] = []
        for mod_dir in sorted(MODULES.iterdir()):
            if not mod_dir.is_dir() or mod_dir.name.startswith("_"):
                continue
            if not (mod_dir / "README.md").exists():
                violations.append(f"modules/{mod_dir.name}/README.md")
        assert not violations, "Missing README.md:\n" + "\n".join(violations)

    def test_modules_have_public_contract(self):
        if not MODULES.exists():
            return
        violations: list[str] = []
        for mod_dir in sorted(MODULES.iterdir()):
            if not mod_dir.is_dir() or mod_dir.name.startswith("_"):
                continue
            contract = mod_dir / "contracts" / "public.py"
            if not contract.exists():
                violations.append(str(contract.relative_to(ROOT)))
        assert not violations, "Missing contracts/public.py:\n" + "\n".join(violations)