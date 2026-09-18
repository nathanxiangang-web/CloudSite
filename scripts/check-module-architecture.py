#!/usr/bin/env python3
"""Validate CloudSite business-module manifests as executable architecture policy."""

from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "apps" / "api" / "cloudsite"
MODULES_ROOT = SOURCE_ROOT / "modules"
PLATFORM_ROOT = SOURCE_ROOT / "platform"

VALID_MIGRATION_STATUS = {"skeleton", "partial", "active"}


@dataclass(frozen=True)
class Manifest:
    path: Path
    name: str
    kind: str
    migration_status: str
    public_contract: str
    allowed_dependencies: tuple[str, ...]
    owned_tables: tuple[str, ...]


def _scalar(lines: list[str], key: str) -> str | None:
    pattern = re.compile(rf"^{re.escape(key)}:\s*(.*?)\s*$")
    for line in lines:
        match = pattern.match(line)
        if not match:
            continue
        value = match.group(1).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        return value
    return None


def _list_value(lines: list[str], key: str) -> tuple[str, ...]:
    start = None
    for index, line in enumerate(lines):
        if line.strip() == f"{key}:" and not line.startswith((" ", "\t")):
            start = index + 1
            break
    if start is None:
        return ()

    values: list[str] = []
    for line in lines[start:]:
        if line and not line.startswith((" ", "\t")):
            break
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not stripped.startswith("- "):
            continue
        value = stripped[2:].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values.append(value)
    return tuple(values)


def _parse_manifest(path: Path) -> tuple[Manifest | None, list[str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    errors: list[str] = []

    schema_version = _scalar(lines, "schema_version")
    name = _scalar(lines, "name")
    kind = _scalar(lines, "kind")
    migration_status = _scalar(lines, "migration_status")
    public_contract = _scalar(lines, "public_contract")

    if schema_version != "1":
        errors.append(f"{path.relative_to(ROOT)}: schema_version must be 1")
    if not name:
        errors.append(f"{path.relative_to(ROOT)}: missing name")
    if not kind:
        errors.append(f"{path.relative_to(ROOT)}: missing kind")
    if not migration_status:
        errors.append(f"{path.relative_to(ROOT)}: missing migration_status")
    if not public_contract:
        errors.append(f"{path.relative_to(ROOT)}: missing public_contract")

    if errors:
        return None, errors

    return (
        Manifest(
            path=path,
            name=name or "",
            kind=kind or "",
            migration_status=migration_status or "",
            public_contract=public_contract or "",
            allowed_dependencies=_list_value(lines, "allowed_dependencies"),
            owned_tables=_list_value(lines, "owned_tables"),
        ),
        errors,
    )


def _module_name(path: Path) -> str:
    rel = path.relative_to(ROOT / "apps" / "api").with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _package_name(path: Path) -> str:
    module = _module_name(path)
    if path.name == "__init__.py":
        return module
    return module.rpartition(".")[0]


def _resolve_from(path: Path, node: ast.ImportFrom) -> str:
    if node.level == 0:
        return node.module or ""

    package_parts = _package_name(path).split(".")
    ascend = node.level - 1
    if ascend > len(package_parts):
        return ""
    base_parts = package_parts[: len(package_parts) - ascend]
    if node.module:
        base_parts.extend(node.module.split("."))
    return ".".join(part for part in base_parts if part)


def _import_targets(path: Path, tree: ast.AST) -> Iterable[str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_from(path, node)
            if not base:
                continue
            for alias in node.names:
                if alias.name == "*":
                    yield base
                else:
                    yield f"{base}.{alias.name}"


def _find_cycles(graph: dict[str, set[str]]) -> list[str]:
    state: dict[str, int] = {node: 0 for node in graph}
    stack: list[str] = []
    cycles: set[str] = set()

    def visit(node: str) -> None:
        state[node] = 1
        stack.append(node)
        for target in sorted(graph[node]):
            if target not in graph:
                continue
            if state[target] == 0:
                visit(target)
            elif state[target] == 1:
                index = stack.index(target)
                cycle_nodes = stack[index:] + [target]
                rotations = []
                body = cycle_nodes[:-1]
                for offset in range(len(body)):
                    rotated = body[offset:] + body[:offset]
                    rotations.append(" -> ".join(rotated + [rotated[0]]))
                cycles.add(min(rotations))
        stack.pop()
        state[node] = 2

    for node in sorted(graph):
        if state[node] == 0:
            visit(node)
    return sorted(cycles)


def validate() -> list[str]:
    errors: list[str] = []
    manifests: dict[str, Manifest] = {}

    module_dirs = [
        path
        for path in sorted(MODULES_ROOT.iterdir())
        if path.is_dir() and not path.name.startswith("_")
    ]

    for module_dir in module_dirs:
        manifest_path = module_dir / "module.yaml"
        if not manifest_path.exists():
            errors.append(f"{manifest_path.relative_to(ROOT)}: missing manifest")
            continue
        manifest, parse_errors = _parse_manifest(manifest_path)
        errors.extend(parse_errors)
        if manifest is None:
            continue

        if manifest.name != module_dir.name:
            errors.append(
                f"{manifest_path.relative_to(ROOT)}: name {manifest.name!r} "
                f"must equal directory {module_dir.name!r}"
            )
        if manifest.kind != "business":
            errors.append(
                f"{manifest_path.relative_to(ROOT)}: kind must be 'business'"
            )
        if manifest.migration_status not in VALID_MIGRATION_STATUS:
            errors.append(
                f"{manifest_path.relative_to(ROOT)}: invalid migration_status "
                f"{manifest.migration_status!r}"
            )
        contract_path = module_dir / manifest.public_contract
        if not contract_path.is_file():
            errors.append(
                f"{manifest_path.relative_to(ROOT)}: public_contract does not exist: "
                f"{manifest.public_contract}"
            )

        manifests[module_dir.name] = manifest

    graph: dict[str, set[str]] = {name: set() for name in manifests}
    table_owners: dict[str, list[str]] = {}

    for name, manifest in manifests.items():
        for table in manifest.owned_tables:
            table_owners.setdefault(table, []).append(name)

        for dependency in manifest.allowed_dependencies:
            if dependency.startswith("modules/"):
                parts = dependency.split("/")
                if len(parts) != 3 or parts[2] != "contracts":
                    errors.append(
                        f"{manifest.path.relative_to(ROOT)}: business dependency must "
                        f"target modules/<name>/contracts: {dependency!r}"
                    )
                    continue
                target = parts[1]
                if target not in manifests:
                    errors.append(
                        f"{manifest.path.relative_to(ROOT)}: unknown module dependency "
                        f"{dependency!r}"
                    )
                    continue
                if target == name:
                    errors.append(
                        f"{manifest.path.relative_to(ROOT)}: module cannot depend on itself"
                    )
                    continue
                graph[name].add(target)
            elif dependency.startswith("platform/"):
                parts = dependency.split("/")
                if len(parts) != 2 or not (PLATFORM_ROOT / parts[1]).is_dir():
                    errors.append(
                        f"{manifest.path.relative_to(ROOT)}: unknown platform dependency "
                        f"{dependency!r}"
                    )
            elif dependency.startswith("plugins/"):
                if not (SOURCE_ROOT / dependency).exists():
                    errors.append(
                        f"{manifest.path.relative_to(ROOT)}: unknown plugin dependency "
                        f"{dependency!r}"
                    )
            else:
                errors.append(
                    f"{manifest.path.relative_to(ROOT)}: unsupported dependency "
                    f"{dependency!r}"
                )

    for table, owners in sorted(table_owners.items()):
        if len(owners) > 1:
            errors.append(
                f"owned table {table!r} has multiple owners: {', '.join(sorted(owners))}"
            )

    for cycle in _find_cycles(graph):
        errors.append(f"business module dependency cycle: {cycle}")

    for name, manifest in manifests.items():
        module_root = MODULES_ROOT / name
        declared = set(manifest.allowed_dependencies)
        for path in sorted(module_root.rglob("*.py")):
            if "tests" in path.relative_to(module_root).parts:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except SyntaxError as exc:
                errors.append(f"{path.relative_to(ROOT)}: cannot parse: {exc}")
                continue

            for target in set(_import_targets(path, tree)):
                prefix = "cloudsite.modules."
                if not target.startswith(prefix):
                    continue
                rest = target[len(prefix):].split(".")
                if len(rest) < 2:
                    continue
                target_module, target_surface = rest[0], rest[1]
                if target_module == name:
                    continue
                if target_surface != "contracts":
                    continue
                expected = f"modules/{target_module}/contracts"
                if expected not in declared:
                    errors.append(
                        f"{path.relative_to(ROOT)}: imports {target!r} but "
                        f"{manifest.path.relative_to(ROOT)} does not allow {expected!r}"
                    )

    return errors


def main() -> int:
    errors = validate()
    if errors:
        print("MODULE ARCHITECTURE VALIDATION FAILED:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print("Module architecture validation PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
