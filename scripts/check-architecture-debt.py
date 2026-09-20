#!/usr/bin/env python3
"""Architecture debt ratchet for the CloudSite 2.0 migration.

The ratchet deliberately does not require the legacy debt to be zero today.
Instead, each known dependency is captured in a reviewed baseline. CI rejects
new dependency surfaces while allowing existing entries to disappear.
"""

from __future__ import annotations

import argparse
import ast
import json
from dataclasses import asdict, dataclass
from pathlib import Path
import subprocess
import sys
from typing import Iterable
import warnings

warnings.filterwarnings("ignore", category=SyntaxWarning)

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "apps" / "api" / "cloudsite"
BASELINE_PATH = ROOT / "docs" / "development" / "architecture-debt-baseline.json"

LEGACY_ROOTS = (
    "cloudsite.models",
    "cloudsite.database",
    "cloudsite.services",
    "cloudsite.main",
)


@dataclass(frozen=True, order=True)
class Debt:
    rule: str
    file: str
    target: str

    @property
    def debt_id(self) -> str:
        return f"{self.rule}::{self.file}::{self.target}"


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


def _legacy_root(target: str) -> str | None:
    for root in LEGACY_ROOTS:
        if target == root or target.startswith(root + "."):
            return root
    return None


def _business_module(path: Path) -> str | None:
    try:
        rel = path.relative_to(SOURCE_ROOT / "modules")
    except ValueError:
        return None
    if len(rel.parts) < 2:
        return None
    return rel.parts[0]


def _cross_module_internal(source_module: str, target: str) -> str | None:
    prefix = "cloudsite.modules."
    if not target.startswith(prefix):
        return None

    rest = target[len(prefix):].split(".")
    if len(rest) < 2:
        return None

    target_module = rest[0]
    if target_module == source_module:
        return None

    target_surface = rest[1]
    if target_surface == "contracts":
        return None

    return ".".join([prefix.rstrip("."), target_module, target_surface])


def collect_debt() -> list[Debt]:
    debts: set[Debt] = set()

    for path in sorted(SOURCE_ROOT.rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        except SyntaxError as exc:
            raise SystemExit(f"Cannot parse {rel}: {exc}") from exc

        targets = set(_import_targets(path, tree))
        source_module = _business_module(path)
        is_router = path.is_relative_to(SOURCE_ROOT / "routers")

        for target in targets:
            legacy = _legacy_root(target)
            if source_module and legacy:
                debts.add(Debt("module_legacy_import", rel, legacy))

            if is_router:
                if target == "sqlalchemy" or target.startswith("sqlalchemy."):
                    debts.add(Debt("router_orm_import", rel, "sqlalchemy"))
                if legacy in {"cloudsite.models", "cloudsite.database"}:
                    debts.add(Debt("router_orm_import", rel, legacy))

            if source_module:
                cross_target = _cross_module_internal(source_module, target)
                if cross_target:
                    debts.add(Debt("cross_module_internal_import", rel, cross_target))

    return sorted(debts)


def baseline_payload(debts: list[Debt]) -> dict[str, object]:
    counts: dict[str, int] = {}
    for debt in debts:
        counts[debt.rule] = counts.get(debt.rule, 0) + 1
    return {
        "schema_version": 1,
        "policy": "Existing architecture debt may be removed but no new debt IDs may be introduced.",
        "counts": dict(sorted(counts.items())),
        "violations": [asdict(debt) | {"id": debt.debt_id} for debt in debts],
    }


def _parse_baseline(text: str, source: str) -> set[str]:
    data = json.loads(text)
    if data.get("schema_version") != 1:
        raise SystemExit(f"Unsupported architecture debt baseline schema_version from {source}.")
    ids = [item["id"] for item in data.get("violations", [])]
    if len(ids) != len(set(ids)):
        raise SystemExit(f"Duplicate architecture debt IDs in baseline from {source}.")
    return set(ids)


def _load_current_baseline() -> set[str]:
    relative = BASELINE_PATH.relative_to(ROOT).as_posix()
    if not BASELINE_PATH.exists():
        raise SystemExit(
            f"Architecture debt baseline missing: {relative}. "
            "Generate it intentionally with --print-baseline, review it, then commit it."
        )
    return _parse_baseline(
        BASELINE_PATH.read_text(encoding="utf-8"),
        relative,
    )


def _load_baseline_from_ref(baseline_ref: str) -> set[str]:
    relative = BASELINE_PATH.relative_to(ROOT).as_posix()
    verify = subprocess.run(
        ["git", "rev-parse", "--verify", baseline_ref],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if verify.returncode != 0:
        raise SystemExit(f"Cannot resolve architecture baseline ref: {baseline_ref}")

    show = subprocess.run(
        ["git", "show", f"{baseline_ref}:{relative}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if show.returncode != 0:
        raise SystemExit(
            f"Architecture debt baseline missing from {baseline_ref}:{relative}"
        )

    print(f"Using previous architecture debt baseline from {baseline_ref}:{relative}")
    return _parse_baseline(show.stdout, f"{baseline_ref}:{relative}")


def check(baseline_ref: str | None = None) -> int:
    current = collect_debt()
    current_ids = {debt.debt_id for debt in current}
    committed_baseline = _load_current_baseline()

    missing_from_baseline = sorted(current_ids - committed_baseline)
    stale_in_baseline = sorted(committed_baseline - current_ids)

    sync_failed = bool(missing_from_baseline or stale_in_baseline)
    if sync_failed:
        print("ARCHITECTURE DEBT BASELINE IS OUT OF SYNC:", file=sys.stderr)
        if missing_from_baseline:
            print("Current debt missing from committed baseline:", file=sys.stderr)
            for debt_id in missing_from_baseline:
                print(f"  - {debt_id}", file=sys.stderr)
        if stale_in_baseline:
            print("Removed debt still present in committed baseline:", file=sys.stderr)
            for debt_id in stale_in_baseline:
                print(f"  - {debt_id}", file=sys.stderr)
        print(
            "Regenerate the exact baseline with --print-baseline after the code change. "
            "The committed baseline must equal the current scanner output.",
            file=sys.stderr,
        )

    introduced: list[str] = []
    previous_count: int | None = None
    if baseline_ref:
        previous_baseline = _load_baseline_from_ref(baseline_ref)
        previous_count = len(previous_baseline)
        introduced = sorted(current_ids - previous_baseline)

    print(
        "Architecture debt: "
        f"current={len(current_ids)} committed={len(committed_baseline)} "
        f"previous={previous_count if previous_count is not None else 'n/a'} "
        f"new={len(introduced)} stale={len(stale_in_baseline)}"
    )

    if introduced:
        print("NEW ARCHITECTURE DEBT IS NOT ALLOWED:", file=sys.stderr)
        for debt_id in introduced:
            print(f"  - {debt_id}", file=sys.stderr)
        print(
            "Updating the current baseline cannot self-approve new debt. Route the "
            "dependency through module contracts/platform boundaries instead.",
            file=sys.stderr,
        )

    if baseline_ref and not introduced and previous_count is not None:
        removed_count = previous_count - len(current_ids)
        if removed_count > 0:
            print(f"Ratchet tightened by {removed_count} debt ID(s).")

    return 1 if sync_failed or introduced else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--print-baseline",
        action="store_true",
        help="Print the exact reviewed JSON baseline payload instead of enforcing it.",
    )
    parser.add_argument(
        "--baseline-ref",
        help="Read the previous enforcement baseline from a git ref. Current committed baseline must also exactly match current debt.",
    )
    args = parser.parse_args()

    debts = collect_debt()
    if args.print_baseline:
        print("__ARCHITECTURE_DEBT_BASELINE_BEGIN__")
        print(json.dumps(baseline_payload(debts), ensure_ascii=False, indent=2))
        print("__ARCHITECTURE_DEBT_BASELINE_END__")
        return 0
    return check(args.baseline_ref)


if __name__ == "__main__":
    raise SystemExit(main())
