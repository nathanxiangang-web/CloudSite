import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const ROOT = process.cwd();

test("catalog list feature owns model/api/styles instead of legacy catalog libs", () => {
  const source = fs.readFileSync(
    path.join(ROOT, "src", "features", "catalog", "views", "CatalogListView.tsx"),
    "utf8",
  );

  assert.doesNotMatch(source, /@\/lib\/catalog(?:-client)?/);
  assert.match(source, /\.\.\/api/);
  assert.match(source, /\.\.\/model/);
  assert.match(source, /catalog-list\.module\.css/);
});

test("catalog public entry exposes the list contract", () => {
  const source = fs.readFileSync(
    path.join(ROOT, "src", "features", "catalog", "index.ts"),
    "utf8",
  );
  assert.match(source, /CatalogListView/);
  assert.match(source, /fetchCatalogEntries/);
  assert.match(source, /catalogEntryHref/);
});

test("catalog list query helpers preserve public API URLs", async () => {
  const catalogModel = await import("../src/features/catalog/model.ts");
  assert.equal(catalogModel.catalogEntryHref("ce_a b/"), "/catalog/ce_a%20b%2F");
  assert.equal(catalogModel.contentTypeLabel("software"), "软件");
  assert.equal(catalogModel.contentTypeLabel("unknown"), "资源");

  const entries = new URL(
    catalogModel.buildCatalogEntriesQuery({
      page: 2,
      page_size: 24,
      content_type: "software",
      tag: "lts",
    }),
    "http://test",
  );
  assert.equal(entries.pathname, "/api/catalog/entries");
  assert.equal(entries.searchParams.get("page"), "2");
  assert.equal(entries.searchParams.get("content_type"), "software");
});
