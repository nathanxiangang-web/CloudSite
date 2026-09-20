"""R1 supplement: Golden Inventory fixture + comparison test.

Implements V2 doc section 74 Golden Inventory comparison: a fixed provider
tree is bootstrapped once, the expected tuple is frozen, and every subsequent
scanner / concurrency / identity / reconcile / search-projection variation is
compared against the golden baseline.  Any drift in the indexing engine that
changes resource_id assignment, path normalization, parent linkage, depth
computation, or directory/file classification will surface here.

Spec provenance: V2 doc section 74; audit-tests-4 P3 gap item 12.
"""
from __future__ import annotations

from typing import Any

from cloudsite.modules.indexing.application.reconcile import ReconcileService
from cloudsite.modules.indexing.application.scan_category import (
    ScanCategoryService,
)
from cloudsite.modules.indexing.domain.snapshot import (
    CategorySnapshot,
    SnapshotEntry,
)
from cloudsite.modules.indexing.infrastructure.alist_adapter import (
    AListProviderAdapter,
    _normalize_path,
    _stable_id,
)
from cloudsite.modules.indexing.infrastructure.repository import IndexedEntry
from cloudsite.modules.providers.contracts.public import ProviderScanRoot
from cloudsite.modules.resources.domain.views import SearchDocumentView


# ---------------------------------------------------------------------------
# Golden tree definition (30 directories + 80 files = 110 entries)
# ---------------------------------------------------------------------------
#
# Layout:
#   /root                                 (dir, depth 0)
#     f00..f07                            (8 files, depth 1)
#     d00..d09                            (10 dirs, depth 1)
#       f00, f01                          (2 files each, depth 2)
#       s0                                (1 dir each, depth 2)
#         f00, f01                        (2 files each, depth 3)
#         x0                              (1 dir each, depth 3)  [only d00..d08]
#           f00, f01, f02                 (3 files each, depth 4) [only d00..d08]
#         f02..f06                        (5 extra files, depth 3) [only d09]
#
# Directories: 1 + 10 + 10 + 9 = 30
# Files:       8 + 20 + 20 + 27 + 5 = 80

_ROOT = "/root"
_ROOT_MAPPING_ID = 1
_CATEGORY_ID = "root:1"


def _golden_dir_specs() -> list[tuple[str, str | None, int]]:
    """Return (path, parent_path, depth) for every golden directory."""
    dirs: list[tuple[str, str | None, int]] = [(_ROOT, None, 0)]
    for i in range(10):
        dirs.append((f"{_ROOT}/d{i:02d}", _ROOT, 1))
    for i in range(10):
        parent = f"{_ROOT}/d{i:02d}"
        dirs.append((f"{parent}/s0", parent, 2))
    for i in range(9):
        parent = f"{_ROOT}/d{i:02d}/s0"
        dirs.append((f"{parent}/x0", parent, 3))
    return dirs


def _golden_file_specs() -> list[tuple[str, str, int]]:
    """Return (path, parent_path, depth) for every golden file."""
    files: list[tuple[str, str, int]] = []
    for j in range(8):
        files.append((f"{_ROOT}/f{j:02d}", _ROOT, 1))
    for i in range(10):
        parent = f"{_ROOT}/d{i:02d}"
        for j in range(2):
            files.append((f"{parent}/f{j:02d}", parent, 2))
    for i in range(10):
        parent = f"{_ROOT}/d{i:02d}/s0"
        for j in range(2):
            files.append((f"{parent}/f{j:02d}", parent, 3))
    for i in range(9):
        parent = f"{_ROOT}/d{i:02d}/s0/x0"
        for j in range(3):
            files.append((f"{parent}/f{j:02d}", parent, 4))
    parent = f"{_ROOT}/d09/s0"
    for j in range(2, 7):
        files.append((f"{parent}/f{j:02d}", parent, 3))
    return files


class _GoldenTree:
    """Fixed 30-directory / 80-file tree with deterministic paths and metadata."""

    root_mapping_id: int = _ROOT_MAPPING_ID
    root_path: str = _ROOT
    category_id: str = _CATEGORY_ID
    content_type: str = "software"

    dir_specs: list[tuple[str, str | None, int]] = _golden_dir_specs()
    file_specs: list[tuple[str, str, int]] = _golden_file_specs()
    num_dirs: int = len(dir_specs)
    num_files: int = len(file_specs)
    total_entries: int = num_dirs + num_files


def _golden_expected() -> tuple[tuple[str, str, bool, str | None, int], ...]:
    """Freeze the expected (resource_id, path, is_dir, parent_id, depth) tuple.

    resource_id and parent_id are computed with the same ``_stable_id`` function
    the adapter uses, so the golden tuple is an independent recomputation from
    the tree definition -- not a capture of scan output -- and will surface any
    drift in id assignment, path normalization, parent linkage, depth, or
    directory/file classification.
    """
    expected: list[tuple[str, str, bool, str | None, int]] = []
    for path, parent_path, depth in _GoldenTree.dir_specs:
        rid = _stable_id("folder", path, _ROOT_MAPPING_ID)
        parent_id = (
            _stable_id("folder", parent_path, _ROOT_MAPPING_ID)
            if parent_path
            else None
        )
        expected.append((rid, _normalize_path(path), True, parent_id, depth))
    for path, parent_path, depth in _GoldenTree.file_specs:
        rid = _stable_id("resource", path, _ROOT_MAPPING_ID)
        parent_id = _stable_id("folder", parent_path, _ROOT_MAPPING_ID)
        expected.append((rid, _normalize_path(path), False, parent_id, depth))
    expected.sort(key=lambda t: (t[4], t[1]))
    return tuple(expected)


_GOLDEN_EXPECTED: tuple[tuple[str, str, bool, str | None, int], ...] = (
    _golden_expected()
)


# ---------------------------------------------------------------------------
# FakeAListProvider + golden tree dict
# ---------------------------------------------------------------------------

class FakeAListProvider:
    """ProviderScanPort fake backed by an in-memory directory tree."""

    def __init__(self, tree: dict[str, list[dict[str, Any]]]) -> None:
        self._tree = tree
        self.list_calls: list[str] = []

    async def list_path(
        self,
        path: str,
        refresh: bool = False,
        strict: bool = False,
    ) -> list[dict[str, Any]]:
        self.list_calls.append(path)
        return list(self._tree.get(path, []))

    async def get_metadata(self, path: str) -> dict[str, Any]:
        return {"name": path.rsplit("/", 1)[-1]}


def _golden_tree_dict() -> dict[str, list[dict[str, Any]]]:
    """Build the FakeAListProvider tree dict from the golden spec."""
    tree: dict[str, list[dict[str, Any]]] = {}
    for path, _parent, _depth in _GoldenTree.dir_specs:
        tree.setdefault(path, [])
    for path, parent, _depth in _GoldenTree.dir_specs:
        if parent is None:
            continue
        name = path.rsplit("/", 1)[-1]
        tree.setdefault(parent, []).append(
            {"name": name, "is_dir": True, "modified": "2024-01-01T00:00:00Z"}
        )
    for path, parent, _depth in _GoldenTree.file_specs:
        name = path.rsplit("/", 1)[-1]
        tree.setdefault(parent, []).append(
            {
                "name": name,
                "is_dir": False,
                "size": 1024,
                "modified": "2024-01-01T00:00:00Z",
            }
        )
    return tree


def _make_root() -> ProviderScanRoot:
    return ProviderScanRoot(
        root_mapping_id=_ROOT_MAPPING_ID,
        content_type=_GoldenTree.content_type,
        storage_path=_ROOT,
        display_name="GoldenRoot",
    )


async def _build_golden_snapshot(
    *,
    concurrency: int = 8,
) -> CategorySnapshot:
    """Build a CategorySnapshot of the golden tree using FakeAListProvider.

    Wires the golden tree dict into a FakeAListProvider, wraps it in the
    AListProviderAdapter, and runs ScanCategoryService to produce the
    snapshot.  This is the canonical golden snapshot all comparisons run
    against.
    """
    provider = FakeAListProvider(_golden_tree_dict())
    adapter = AListProviderAdapter(provider, [_make_root()])
    scan_service = ScanCategoryService(adapter)
    scan_result = await scan_service.scan(_CATEGORY_ID)
    return scan_result.snapshot


async def _scan_golden(
    *,
    concurrency: int = 8,
) -> tuple[list[SnapshotEntry], bool]:
    """Scan the golden tree and return (entries, pagination_complete)."""
    provider = FakeAListProvider(_golden_tree_dict())
    adapter = AListProviderAdapter(provider, [_make_root()])
    entries, _, complete = await adapter.scan_category(
        _CATEGORY_ID, concurrency=concurrency
    )
    return entries, complete


def _entry_tuple(entry: SnapshotEntry) -> tuple[str, str, bool, str | None, int]:
    """Project a SnapshotEntry to the golden comparison tuple."""
    meta = entry.metadata or {}
    return (
        entry.resource_id,
        entry.path,
        bool(meta.get("is_dir")),
        meta.get("parent_id"),
        int(meta.get("depth", 0)),
    )


# ---------------------------------------------------------------------------
# In-memory IndexingStore for reconcile tests
# ---------------------------------------------------------------------------

class _InMemoryStore:
    """In-memory IndexingStore implementation for golden reconcile tests."""

    def __init__(self) -> None:
        self._entries: dict[str, IndexedEntry] = {}

    async def list_indexed(
        self, *, category_id: str, provider_id: str
    ) -> list[IndexedEntry]:
        return [
            e
            for e in self._entries.values()
            if e.category_id == category_id and e.provider_id == provider_id
        ]

    async def upsert(self, entries: list[IndexedEntry]) -> int:
        for e in entries:
            self._entries[e.resource_id] = e
        return len(entries)

    async def remove(self, resource_ids: list[str]) -> int:
        removed = 0
        for rid in resource_ids:
            if rid in self._entries:
                del self._entries[rid]
                removed += 1
        return removed

    async def touch_unchanged(self, resource_ids: list[str]) -> int:
        return len(resource_ids)

    def existing_ids(self) -> set[str]:
        return set(self._entries.keys())


# ---------------------------------------------------------------------------
# Search projection helper
# ---------------------------------------------------------------------------

def _to_search_document(entry: SnapshotEntry) -> SearchDocumentView:
    """Project a golden SnapshotEntry to a SearchDocumentView.

    Mirrors the folder/resource projection in
    modules/resources/infrastructure/query_repository.py: object_id is the
    resource_id, object_type is "folder" or "resource", extension is the file
    suffix for files and "" for folders, content_type comes from metadata, and
    breadcrumb_text is the full path.
    """
    meta = entry.metadata or {}
    is_dir = bool(meta.get("is_dir"))
    name = entry.name
    extension = ""
    if not is_dir and "." in name:
        extension = name.rsplit(".", 1)[-1].lower()
    return SearchDocumentView(
        object_id=entry.resource_id,
        object_type="folder" if is_dir else "resource",
        name=name,
        extension=extension,
        content_type=str(meta.get("content_type") or ""),
        breadcrumb_text=entry.path,
    )


# ---------------------------------------------------------------------------
# Sanity checks on the golden fixture itself
# ---------------------------------------------------------------------------

def test_golden_fixture_shape() -> None:
    """The golden fixture has exactly 30 directories and 80 files."""
    assert _GoldenTree.num_dirs == 30
    assert _GoldenTree.num_files == 80
    assert _GoldenTree.total_entries == 110
    assert len(_GOLDEN_EXPECTED) == 110


def test_golden_fixture_paths_unique() -> None:
    """Every golden path is unique."""
    paths = [t[1] for t in _GOLDEN_EXPECTED]
    assert len(set(paths)) == len(paths)


# ---------------------------------------------------------------------------
# 1. Golden inventory matches expected
# ---------------------------------------------------------------------------

async def test_golden_inventory_matches_expected() -> None:
    """Scanning the golden tree produces exactly the frozen expected tuple."""
    entries, complete = await _scan_golden(concurrency=8)
    assert complete is True
    assert len(entries) == len(_GOLDEN_EXPECTED)

    actual = sorted(
        (_entry_tuple(e) for e in entries),
        key=lambda t: (t[4], t[1]),
    )
    assert tuple(actual) == _GOLDEN_EXPECTED


# ---------------------------------------------------------------------------
# 2. Concurrency=1 matches golden
# ---------------------------------------------------------------------------

async def test_golden_concurrency_1_matches_golden() -> None:
    """A serial (concurrency=1) scan produces the same tuple as the golden."""
    entries, complete = await _scan_golden(concurrency=1)
    assert complete is True
    assert len(entries) == len(_GOLDEN_EXPECTED)

    actual = sorted(
        (_entry_tuple(e) for e in entries),
        key=lambda t: (t[4], t[1]),
    )
    assert tuple(actual) == _GOLDEN_EXPECTED


# ---------------------------------------------------------------------------
# 3. Concurrency=8 matches golden
# ---------------------------------------------------------------------------

async def test_golden_concurrency_8_matches_golden() -> None:
    """A concurrency=8 scan produces the same tuple as the golden."""
    entries, complete = await _scan_golden(concurrency=8)
    assert complete is True
    assert len(entries) == len(_GOLDEN_EXPECTED)

    actual = sorted(
        (_entry_tuple(e) for e in entries),
        key=lambda t: (t[4], t[1]),
    )
    assert tuple(actual) == _GOLDEN_EXPECTED


# ---------------------------------------------------------------------------
# 4. Idempotent: second scan produces no changes
# ---------------------------------------------------------------------------

async def test_golden_idempotent() -> None:
    """Two consecutive scan+reconcile passes: the second issues no changes."""
    store = _InMemoryStore()
    provider = FakeAListProvider(_golden_tree_dict())
    adapter = AListProviderAdapter(provider, [_make_root()])
    scan_service = ScanCategoryService(adapter)
    reconcile_service = ReconcileService(store)

    first_scan = await scan_service.scan(_CATEGORY_ID)
    first_reconcile = await reconcile_service.reconcile(first_scan.snapshot)
    assert first_reconcile.writes.added == len(_GOLDEN_EXPECTED)
    assert first_reconcile.writes.changed == 0
    assert first_reconcile.writes.removed == 0
    assert len(store.existing_ids()) == len(_GOLDEN_EXPECTED)

    second_scan = await scan_service.scan(_CATEGORY_ID)
    second_reconcile = await reconcile_service.reconcile(second_scan.snapshot)
    assert second_reconcile.writes.added == 0
    assert second_reconcile.writes.changed == 0
    assert second_reconcile.writes.removed == 0
    assert second_reconcile.writes.unchanged == len(_GOLDEN_EXPECTED)
    assert len(store.existing_ids()) == len(_GOLDEN_EXPECTED)


# ---------------------------------------------------------------------------
# 5. Reconcile preserves inventory matching golden
# ---------------------------------------------------------------------------

async def test_golden_reconcile_preserves_inventory() -> None:
    """After reconcile, the persisted inventory matches the golden tuple."""
    store = _InMemoryStore()
    provider = FakeAListProvider(_golden_tree_dict())
    adapter = AListProviderAdapter(provider, [_make_root()])
    scan_service = ScanCategoryService(adapter)
    reconcile_service = ReconcileService(store)

    scan_result = await scan_service.scan(_CATEGORY_ID)
    await reconcile_service.reconcile(scan_result.snapshot)

    persisted = await store.list_indexed(
        category_id=_CATEGORY_ID,
        provider_id=adapter.provider_id,
    )
    assert len(persisted) == len(_GOLDEN_EXPECTED)

    actual = sorted(
        (
            (
                e.resource_id,
                e.path,
                bool((e.metadata or {}).get("is_dir")),
                (e.metadata or {}).get("parent_id"),
                int((e.metadata or {}).get("depth", 0)),
            )
            for e in persisted
        ),
        key=lambda t: (t[4], t[1]),
    )
    assert tuple(actual) == _GOLDEN_EXPECTED


# ---------------------------------------------------------------------------
# 6. Search projection complete
# ---------------------------------------------------------------------------

async def test_golden_search_projection_complete() -> None:
    """Every golden entry has a corresponding search projection document."""
    entries, complete = await _scan_golden(concurrency=8)
    assert complete is True

    documents = [_to_search_document(e) for e in entries]
    assert len(documents) == len(_GOLDEN_EXPECTED)

    projected_ids = {doc.object_id for doc in documents}
    golden_ids = {t[0] for t in _GOLDEN_EXPECTED}
    assert projected_ids == golden_ids

    for doc, entry in zip(documents, entries):
        meta = entry.metadata or {}
        is_dir = bool(meta.get("is_dir"))
        assert doc.object_type == ("folder" if is_dir else "resource")
        assert doc.name == entry.name
        assert doc.content_type == _GoldenTree.content_type
        assert doc.breadcrumb_text == entry.path
        if not is_dir:
            assert isinstance(doc.extension, str)
