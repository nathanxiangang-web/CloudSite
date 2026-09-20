import assert from "node:assert/strict";
import test from "node:test";

import { normalizeSyncInterval } from "../src/lib/sync-interval.ts";


test("normalizeSyncInterval preserves 180 from legacy settings", () => {
  assert.equal(normalizeSyncInterval(180), 180);
});

test("normalizeSyncInterval preserves 360/720/1440", () => {
  assert.equal(normalizeSyncInterval(360), 360);
  assert.equal(normalizeSyncInterval(720), 720);
  assert.equal(normalizeSyncInterval(1440), 1440);
});

test("normalizeSyncInterval falls back to 360 for invalid values", () => {
  assert.equal(normalizeSyncInterval(0), 360);
  assert.equal(normalizeSyncInterval(60), 360);
  assert.equal(normalizeSyncInterval(999), 360);
});