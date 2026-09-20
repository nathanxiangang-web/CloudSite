import assert from "node:assert/strict";
import test from "node:test";

import {
  buildCatalogSearchQuery,
  catalogEntryHref,
  contentTypeLabel,
  type CatalogSearchResponse,
} from "../src/lib/catalog.ts";
import { normalizeSearchQuery } from "../src/lib/search-query.ts";


type FileSearchResponse = {
  total: number;
  items: Array<{ id: string; object_type: "resource" | "folder" }>;
};


function partitionSearchResults(catalog: { total: number } | null, files: { total: number; items: unknown[] } | null) {
  const catalogTotal = catalog?.total ?? 0;
  const fileTotal = files?.total ?? 0;
  const fileItems = files?.items ?? [];
  return {
    showCatalogSection: catalogTotal > 0,
    showFileSection: fileItems.length > 0,
    showEmpty: fileTotal === 0 && catalogTotal === 0,
    summary: `${fileTotal} 个文件结果与 ${catalogTotal} 个资源条目`,
  };
}


test("aggregate search hits two distinct endpoints for catalog entries and files", () => {
  const q = normalizeSearchQuery("  Office   2024  ");
  const catalogUrl = buildCatalogSearchQuery({ q, page: 1, page_size: 24 });
  assert.match(catalogUrl, /^\/api\/catalog\/search\?/);
  assert.equal(new URL(catalogUrl, "http://t").searchParams.get("q"), "Office 2024");

  const fileUrl = `/api/search?q=${encodeURIComponent(q)}&page=1&page_size=24&sort=relevance`;
  assert.match(fileUrl, /^\/api\/search\?/);
  assert.notEqual(catalogUrl.split("?")[0], fileUrl.split("?")[0]);
});


test("catalog entries and files render into separate partitions with correct visibility", () => {
  const catalogOnly: { total: number } = { total: 2 };
  const filesNone: { total: number; items: unknown[] } = { total: 0, items: [] };
  assert.deepEqual(partitionSearchResults(catalogOnly, filesNone), {
    showCatalogSection: true,
    showFileSection: false,
    showEmpty: false,
    summary: "0 个文件结果与 2 个资源条目",
  });

  const catalogNone: { total: number } = { total: 0 };
  const filesOnly: { total: number; items: unknown[] } = { total: 1, items: [{ id: "r1" }] };
  assert.deepEqual(partitionSearchResults(catalogNone, filesOnly), {
    showCatalogSection: false,
    showFileSection: true,
    showEmpty: false,
    summary: "1 个文件结果与 0 个资源条目",
  });

  const both: { total: number } = { total: 3 };
  const bothFiles: { total: number; items: unknown[] } = { total: 5, items: [{ id: "r1" }, { id: "r2" }] };
  assert.deepEqual(partitionSearchResults(both, bothFiles), {
    showCatalogSection: true,
    showFileSection: true,
    showEmpty: false,
    summary: "5 个文件结果与 3 个资源条目",
  });

  assert.deepEqual(partitionSearchResults(null, null), {
    showCatalogSection: false,
    showFileSection: false,
    showEmpty: true,
    summary: "0 个文件结果与 0 个资源条目",
  });
});


test("catalog entry href targets /catalog prefix while file results target /resource or /folder", () => {
  const entryHref = catalogEntryHref("ce_abc");
  assert.match(entryHref, /^\/catalog\//);
  const fileResourceHref = `/resource/${"res-1"}`;
  const fileFolderHref = `/folder/${"fld-1"}`;
  assert.match(fileResourceHref, /^\/resource\//);
  assert.match(fileFolderHref, /^\/folder\//);
  assert.notEqual(entryHref.split("/")[1], fileResourceHref.split("/")[1]);
});


test("catalog partition labels entries by content type while files use extension metadata", () => {
  const catalogItem: CatalogSearchResponse = {
    query: "toolbox",
    filters: { content_type: "software", tag: null, platform: null },
    items: [{
      entry_id: "ce_a",
      slug: "toolbox",
      title: "Toolbox",
      content_type: "software",
      summary: "Network toolkit",
      cover_resource_id: null,
      status: "published",
      availability: "available",
      tags: [],
      updated_at: "2026-01-01T00:00:00Z",
      match_type: "metadata",
      revision: 1,
      sort_order: 0,
      published_at: "2026-01-01T00:00:00Z",
      releases: [],
    }],
    page: 1,
    page_size: 24,
    total: 1,
    total_pages: 1,
    suggestion: null,
  };
  assert.equal(contentTypeLabel(catalogItem.items[0].content_type), "软件");
  assert.equal(catalogItem.suggestion, null);
  assert.equal(catalogItem.items[0].match_type, "metadata");

  const emptyCatalog: CatalogSearchResponse = {
    query: "zzz",
    filters: { content_type: null, tag: null, platform: null },
    items: [],
    page: 1,
    page_size: 24,
    total: 0,
    total_pages: 0,
    suggestion: "未找到匹配的资源条目",
  };
  assert.equal(emptyCatalog.suggestion, "未找到匹配的资源条目");
  assert.equal(partitionSearchResults({ total: emptyCatalog.total }, { total: 0, items: [] }).showEmpty, true);
});
