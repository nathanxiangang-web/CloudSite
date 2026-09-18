import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const ROOT = process.cwd();

test("catalog route is a thin feature composition", () => {
  const source = fs.readFileSync(
    path.join(ROOT, "src", "app", "catalog", "page.tsx"),
    "utf8",
  );

  assert.match(source, /@\/features\/catalog/);
  assert.doesNotMatch(source, /@\/features\/catalog\//);
  assert.doesNotMatch(source, /@\/lib\/catalog/);
  assert.doesNotMatch(source, /@tanstack\/react-query/);
});

test("catalog feature manifest declares the public route", () => {
  const manifest = JSON.parse(
    fs.readFileSync(
      path.join(ROOT, "src", "features", "catalog", "feature.json"),
      "utf8",
    ),
  );

  assert.equal(manifest.schema_version, 1);
  assert.equal(manifest.name, "catalog");
  assert.equal(manifest.migration_status, "partial");
  assert.equal(manifest.public_entry, "index.ts");
  assert.deepEqual(manifest.routes, [
    "/catalog",
    "/catalog/[entryId]",
    "/account/follows",
  ]);
});
