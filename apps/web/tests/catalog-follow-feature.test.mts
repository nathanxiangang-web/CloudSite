import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

test("account follows route composes Catalog only through the public entry", () => {
  const source = fs.readFileSync(
    new URL("../src/app/account/follows/page.tsx", import.meta.url),
    "utf8",
  );
  assert.match(source, /@\/features\/catalog/);
  assert.doesNotMatch(source, /@\/features\/catalog\//);
  assert.doesNotMatch(source, /@\/lib\/catalog/);
  assert.doesNotMatch(source, /@tanstack\/react-query/);
});

test("legacy CatalogFollowButton path is only a feature re-export", () => {
  const source = fs.readFileSync(
    new URL("../src/components/catalog/CatalogFollowButton.tsx", import.meta.url),
    "utf8",
  );
  assert.equal(source.trim(), 'export { CatalogFollowButton } from "@/features/catalog";');
});

test("Catalog detail view owns the follow component inside the feature", () => {
  const source = fs.readFileSync(
    new URL("../src/features/catalog/views/CatalogDetailView.tsx", import.meta.url),
    "utf8",
  );
  assert.match(source, /\.\.\/components\/CatalogFollowButton/);
  assert.doesNotMatch(source, /followSlot/);
});
