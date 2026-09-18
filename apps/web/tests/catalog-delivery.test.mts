import assert from "node:assert/strict";
import test from "node:test";

import {
  assetDimensionLabel,
  entryIsAvailable,
  pickDownloadLocation,
  releaseIsHistorical,
  releaseIsPublished,
  releaseIsRecommended,
  type CatalogAssetSummary,
  type CatalogLocation,
  type CatalogReleaseSummary,
} from "../src/features/catalog/model.ts";


function makeRelease(over: Partial<CatalogReleaseSummary> = {}): CatalogReleaseSummary {
  return {
    release_id: "cr_x",
    slug: "v1",
    title: "V1",
    channel: "stable",
    is_recommended: false,
    release_date: null,
    status: "published",
    published_at: "2026-01-01T00:00:00Z",
    ...over,
  };
}


function makeAsset(over: Partial<CatalogAssetSummary> = {}): CatalogAssetSummary {
  return {
    asset_id: "ca_x",
    slug: "a",
    display_name: "A",
    platform: "windows",
    kind: "archive",
    architecture: "x64",
    package_type: "zip",
    language: "unknown",
    build_label: "",
    size: 100,
    status: "active",
    availability: "available",
    location_count: 1,
    ...over,
  };
}


test("release picker puts recommended release first and historical last", () => {
  const releases: CatalogReleaseSummary[] = [
    makeRelease({ release_id: "cr_a", slug: "v1", title: "V1", channel: "stable", is_recommended: false, published_at: "2026-01-01T00:00:00Z" }),
    makeRelease({ release_id: "cr_b", slug: "v2", title: "V2", channel: "historical", is_recommended: false, published_at: "2026-02-01T00:00:00Z" }),
    makeRelease({ release_id: "cr_c", slug: "v3", title: "V3", channel: "stable", is_recommended: true, published_at: "2026-03-01T00:00:00Z" }),
  ];
  const recommended = releases.find(releaseIsRecommended);
  const rest = releases.filter((release) => !releaseIsRecommended(release));
  rest.sort((a, b) => (releaseIsHistorical(b) ? -1 : 0) - (releaseIsHistorical(a) ? -1 : 0));
  const sorted = recommended ? [recommended, ...rest] : rest;

  assert.equal(sorted[0].release_id, "cr_c");
  assert.equal(sorted[sorted.length - 1].release_id, "cr_b");
  assert.equal(sorted.length, 3);
});


test("release picker without recommended keeps historical last", () => {
  const releases: CatalogReleaseSummary[] = [
    makeRelease({ release_id: "cr_a", channel: "stable" }),
    makeRelease({ release_id: "cr_b", channel: "historical" }),
    makeRelease({ release_id: "cr_c", channel: "beta" }),
  ];
  const recommended = releases.find(releaseIsRecommended);
  const rest = releases.filter((release) => !releaseIsRecommended(release));
  rest.sort((a, b) => (releaseIsHistorical(b) ? -1 : 0) - (releaseIsHistorical(a) ? -1 : 0));
  const sorted = recommended ? [recommended, ...rest] : rest;

  assert.equal(sorted[sorted.length - 1].release_id, "cr_b");
  assert.equal(sorted[0].release_id, "cr_a");
});


test("release picker only shows published releases", () => {
  const releases: CatalogReleaseSummary[] = [
    makeRelease({ release_id: "cr_a", status: "published" }),
    makeRelease({ release_id: "cr_b", status: "draft" }),
    makeRelease({ release_id: "cr_c", status: "archived" }),
  ];
  const visible = releases.filter(releaseIsPublished);
  assert.deepEqual(visible.map((r) => r.release_id), ["cr_a"]);
});


test("asset dimension labels fall back for unknown or empty values", () => {
  assert.equal(assetDimensionLabel("unknown", "通用"), "通用");
  assert.equal(assetDimensionLabel("", "通用"), "通用");
  assert.equal(assetDimensionLabel("x64", "未知"), "x64");
  assert.equal(assetDimensionLabel("windows", "通用"), "windows");
  assert.equal(assetDimensionLabel("arm64", "未知"), "arm64");
});


test("asset filter narrows by platform and architecture using normalized values", () => {
  const assets: CatalogAssetSummary[] = [
    makeAsset({ asset_id: "ca_a", platform: "windows", architecture: "x64", package_type: "zip" }),
    makeAsset({ asset_id: "ca_b", platform: "linux", architecture: "x64", package_type: "tar" }),
    makeAsset({ asset_id: "ca_c", platform: "windows", architecture: "arm64", package_type: "zip" }),
    makeAsset({ asset_id: "ca_d", platform: "", architecture: "unknown", package_type: "unknown" }),
  ];
  const filter = (list: CatalogAssetSummary[], platform: string, arch: string) =>
    list.filter(
      (asset) =>
        (!platform || (asset.platform || "通用") === platform) &&
        (!arch || (asset.architecture || "unknown") === arch),
    );

  assert.equal(filter(assets, "windows", "").length, 2);
  assert.equal(filter(assets, "windows", "x64").length, 1);
  assert.equal(filter(assets, "linux", "").length, 1);
  assert.equal(filter(assets, "", "arm64").length, 1);
  assert.equal(filter(assets, "通用", "").length, 1);
  assert.equal(filter(assets, "", "unknown").length, 1);
  assert.equal(filter(assets, "", "").length, 4);
});


test("unavailable asset renders disabled state with reason and no download location", () => {
  const unavailable = makeAsset({ asset_id: "ca_off", availability: "unavailable", status: "disabled" });
  const label = unavailable.availability === "available" ? "可下载" : "暂不可用";
  assert.equal(label, "暂不可用");
  assert.equal(unavailable.availability === "available", false);

  const locations: CatalogLocation[] = [
    { location_id: "cl_a", resource_id: "r_a", root_mapping_id: null, label: "dead", is_primary: false, status: "disabled", availability: "unavailable", download_url: "", resource: null },
    { location_id: "cl_b", resource_id: "r_b", root_mapping_id: null, label: "inactive", is_primary: true, status: "active", availability: "unavailable", download_url: "", resource: null },
  ];
  assert.equal(pickDownloadLocation(locations), null);
  assert.equal(pickDownloadLocation([]), null);
});


test("available asset with primary location picks a downloadable location", () => {
  const locations: CatalogLocation[] = [
    { location_id: "cl_a", resource_id: "r_a", root_mapping_id: 1, label: "mirror", is_primary: false, status: "active", availability: "available", download_url: "/d/r_a", resource: null },
    { location_id: "cl_b", resource_id: "r_b", root_mapping_id: 1, label: "main", is_primary: true, status: "active", availability: "available", download_url: "/d/r_b", resource: null },
  ];
  const picked = pickDownloadLocation(locations);
  assert.equal(picked?.location_id, "cl_b");
  assert.equal(picked?.download_url, "/d/r_b");
});


test("entry availability guard requires published status and available state", () => {
  assert.equal(entryIsAvailable({ availability: "available", status: "published" }), true);
  assert.equal(entryIsAvailable({ availability: "unavailable", status: "published" }), false);
  assert.equal(entryIsAvailable({ availability: "available", status: "draft" }), false);
});
