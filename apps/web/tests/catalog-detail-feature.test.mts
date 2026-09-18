import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const ROOT = process.cwd();

test("catalog detail route is a thin feature composition", () => {
  const source = fs.readFileSync(
    path.join(ROOT, "src", "app", "catalog", "[entryId]", "page.tsx"),
    "utf8",
  );
  assert.match(source, /@\/features\/catalog/);
  assert.doesNotMatch(source, /@\/features\/catalog\//);
  assert.doesNotMatch(source, /@\/lib\/catalog/);
  assert.doesNotMatch(source, /@tanstack\/react-query/);
  assert.doesNotMatch(source, /react-markdown/);
});

test("catalog detail view owns its API model and styles", () => {
  const source = fs.readFileSync(
    path.join(ROOT, "src", "features", "catalog", "views", "CatalogDetailView.tsx"),
    "utf8",
  );
  assert.doesNotMatch(source, /@\/lib\/catalog(?:-client)?/);
  assert.match(source, /\.\.\/api/);
  assert.match(source, /\.\.\/model/);
  assert.match(source, /catalog-detail\.module\.css/);
});

test("catalog detail helpers preserve legacy delivery behavior", async () => {
  const catalogModel = await import("../src/features/catalog/model.ts");
  const catalogApi = await import("../src/features/catalog/api.ts");

  assert.equal(catalogModel.assetKindLabel("archive"), "压缩包");
  assert.equal(catalogModel.assetDimensionLabel("unknown", "未知"), "未知");
  assert.equal(catalogModel.releaseIsPublished({ status: "published" }), true);
  assert.equal(catalogModel.releaseIsHistorical({ channel: "historical" }), true);
  assert.equal(
    catalogApi.catalogAssetDownloadPath("ce a", "ca/1"),
    "/api/catalog/entries/ce%20a/assets/ca%2F1/download",
  );
});

test("catalog manifest owns list and detail routes", () => {
  const manifest = JSON.parse(
    fs.readFileSync(
      path.join(ROOT, "src", "features", "catalog", "feature.json"),
      "utf8",
    ),
  );
  assert.deepEqual(manifest.routes, ["/catalog", "/catalog/[entryId]"]);
});
