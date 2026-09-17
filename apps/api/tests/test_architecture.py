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