import assert from "node:assert/strict";
import test from "node:test";

import {
  assetKindLabel,
  buildCatalogEntriesQuery,
  catalogAssetHref,
  catalogEntryHref,
  catalogReleaseHref,
  contentTypeLabel,
  entryIsAvailable,
  pickDownloadLocation,
  releaseIsPublished,
  statusLabel,
} from "../src/features/catalog/model.ts";


test("catalog href helpers encode IDs and keep paths under /catalog", () => {
  assert.equal(catalogEntryHref("ce_abc"), "/catalog/ce_abc");
  assert.equal(catalogEntryHref("ce_a b/"), "/catalog/ce_a%20b%2F");
  assert.equal(catalogReleaseHref("cr_1"), "/catalog/releases/cr_1");
  assert.equal(catalogAssetHref("ca_1"), "/catalog/assets/ca_1");
});


test("pickDownloadLocation prefers primary, then first available, never unavailable", () => {
  const locations = [
    { location_id: "cl_a", resource_id: "r_a", root_mapping_id: null, label: "mirror", is_primary: false, status: "active" as const, availability: "available" as const, download_url: "/d/r_a", resource: null },
    { location_id: "cl_b", resource_id: "r_b", root_mapping_id: null, label: "main", is_primary: true, status: "active" as const, availability: "available" as const, download_url: "/d/r_b", resource: null },
    { location_id: "cl_c", resource_id: "r_c", root_mapping_id: null, label: "dead", is_primary: false, status: "disabled" as const, availability: "unavailable" as const, download_url: "/d/r_c", resource: null },
  ];
  const picked = pickDownloadLocation(locations);
  assert.equal(picked?.location_id, "cl_b");
  assert.equal(pickDownloadLocation([]), null);
  assert.equal(pickDownloadLocation([locations[2]]), null);
});


test("availability guards require published status and available state", () => {
  assert.equal(entryIsAvailable({ availability: "available", status: "published" }), true);
  assert.equal(entryIsAvailable({ availability: "available", status: "draft" }), false);
  assert.equal(entryIsAvailable({ availability: "unavailable", status: "published" }), false);
  assert.equal(releaseIsPublished({ status: "published" }), true);
  assert.equal(releaseIsPublished({ status: "draft" }), false);
});


test("label helpers fall back gracefully for unknown values", () => {
  assert.equal(contentTypeLabel("software"), "软件");
  assert.equal(contentTypeLabel("unknown-type"), "资源");
  assert.equal(assetKindLabel("archive"), "压缩包");
  assert.equal(statusLabel("draft"), "草稿");
  assert.equal(statusLabel("published"), "已发布");
});


test("buildCatalogEntriesQuery builds a query string only for provided filters", () => {
  const path = buildCatalogEntriesQuery({ page: 2, content_type: "software", tag: "lts" });
  assert.match(path, /^\/api\/catalog\/entries\?/);
  const search = new URL(path, "http://t").searchParams;
  assert.equal(search.get("page"), "2");
  assert.equal(search.get("content_type"), "software");
  assert.equal(search.get("tag"), "lts");

  const empty = buildCatalogEntriesQuery({});
  assert.equal(empty, "/api/catalog/entries");

  const paged = buildCatalogEntriesQuery({ page: 3, page_size: 24 });
  const pagedSearch = new URL(paged, "http://t").searchParams;
  assert.equal(pagedSearch.get("page"), "3");
  assert.equal(pagedSearch.get("page_size"), "24");
  assert.equal(pagedSearch.has("content_type"), false);
  assert.equal(pagedSearch.has("tag"), false);
});
