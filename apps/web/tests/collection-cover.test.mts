import assert from "node:assert/strict";
import test from "node:test";

import { collectionCoverSrc } from "../src/lib/collection-cover.ts";

test("uses a valid resource ID as a collection cover", () => {
  assert.equal(collectionCoverSrc("r_5285dea95b2338f81be157d0464262e4", "/fallback.webp"), "/p/r_5285dea95b2338f81be157d0464262e4");
});

test("falls back for empty or path-like cover values", () => {
  assert.equal(collectionCoverSrc("", "/fallback.webp"), "/fallback.webp");
  assert.equal(collectionCoverSrc("/", "/fallback.webp"), "/fallback.webp");
  assert.equal(collectionCoverSrc("../../image", "/fallback.webp"), "/fallback.webp");
});
