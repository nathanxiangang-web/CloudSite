import assert from "node:assert/strict";
import test from "node:test";

import { isRollingFixedSchedule, normalizeSyncInterval } from "../src/lib/sync-interval.ts";


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

test("isRollingFixedSchedule true only for 1.1 with completed initial index", () => {
  assert.equal(isRollingFixedSchedule({ sync_engine_version: "1.1", initial_index_completed_at: "2026-09-01T00:00:00Z" }), true);
});

test("isRollingFixedSchedule false for legacy or incomplete index", () => {
  assert.equal(isRollingFixedSchedule({ sync_engine_version: "1.0", initial_index_completed_at: "2026-09-01T00:00:00Z" }), false);
  assert.equal(isRollingFixedSchedule({ sync_engine_version: "1.1", initial_index_completed_at: null }), false);
  assert.equal(isRollingFixedSchedule({ sync_engine_version: "1.1" }), false);
  assert.equal(isRollingFixedSchedule({}), false);
});
