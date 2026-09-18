import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

import {
  assetDimensionLabel,
  catalogAssetDownloadPath,
  releaseIsHistorical,
  releaseIsPublished,
  releaseIsRecommended,
} from "../src/features/catalog/model.ts";

test("catalog detail helpers preserve release and download behavior", () => {
  assert.equal(releaseIsPublished({ status: "published" }), true);
  assert.equal(releaseIsPublished({ status: "draft" }), false);
  assert.equal(releaseIsRecommended({ is_recommended: true }), true);
  assert.equal(releaseIsHistorical({ channel: "historical" }), true);
  assert.equal(assetDimensionLabel("unknown", "未知"), "未知");
  assert.equal(assetDimensionLabel("x64", "未知"), "x64");
  assert.equal(
    catalogAssetDownloadPath("ce a", "ca/b"),
    "/api/catalog/entries/ce%20a/assets/ca%2Fb/download",
  );
});

test("catalog detail route is a thin public-entry composition", () => {
  const source = fs.readFileSync(
    new URL("../src/app/catalog/[entryId]/page.tsx", import.meta.url),
    "utf8",
  );
  assert.match(source, /@\/features\/catalog/);
  assert.doesNotMatch(source, /@\/features\/catalog\//);
  assert.doesNotMatch(source, /@\/lib\/catalog/);
  assert.doesNotMatch(source, /@tanstack\/react-query/);
  assert.doesNotMatch(source, /CatalogFollowButton/);
});
