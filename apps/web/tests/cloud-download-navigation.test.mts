import assert from "node:assert/strict";
import test from "node:test";

import {
  CLOUD_DOWNLOAD_HREF,
  CLOUD_DOWNLOAD_LABEL,
  mapLegacyBrowseToCloudDownload,
} from "../src/lib/navigation.ts";


test("mapLegacyBrowseToCloudDownload rewrites the legacy browse item to cloud-download", () => {
  const result = mapLegacyBrowseToCloudDownload({ href: "/browse", label: "\u6d4f\u89c8", sort_order: 4 });
  assert.equal(result.href, CLOUD_DOWNLOAD_HREF);
  assert.equal(result.label, CLOUD_DOWNLOAD_LABEL);
  assert.equal(result.sort_order, 4);
});


test("mapLegacyBrowseToCloudDownload leaves non-browse items untouched", () => {
  const item = { href: "/resources/software", label: "\u8d44\u6e90\u5e93", sort_order: 1 };
  const result = mapLegacyBrowseToCloudDownload(item);
  assert.equal(result.href, "/resources/software");
  assert.equal(result.label, "\u8d44\u6e90\u5e93");
  assert.equal(result, item);
});


test("mapLegacyBrowseToCloudDownload does not rewrite browse href with a different label", () => {
  const result = mapLegacyBrowseToCloudDownload({ href: "/browse", label: "\u5168\u90e8\u8d44\u6e90" });
  assert.equal(result.href, "/browse");
  assert.equal(result.label, "\u5168\u90e8\u8d44\u6e90");
});


test("cloud-download constants point at the new page and Chinese label", () => {
  assert.equal(CLOUD_DOWNLOAD_HREF, "/cloud-download");
  assert.equal(CLOUD_DOWNLOAD_LABEL, "\u4e91\u4e0b\u8f7d");
});
