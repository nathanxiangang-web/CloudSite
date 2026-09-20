import assert from "node:assert/strict";
import test from "node:test";

import { formatTime, mapMediaError, compatibilityHint, pictureInPictureSupported } from "../src/components/video/video-utils.ts";

test("formatTime renders mm:ss and hh:mm:ss", () => {
  assert.equal(formatTime(0), "00:00");
  assert.equal(formatTime(65), "01:05");
  assert.equal(formatTime(3661), "1:01:01");
  assert.equal(formatTime(NaN), "00:00");
  assert.equal(formatTime(-5), "00:00");
});

test("mapMediaError maps numeric MediaError codes to stable kinds", () => {
  assert.equal(mapMediaError({ code: 1 }).kind, "source_not_supported");
  assert.equal(mapMediaError({ code: 2 }).kind, "network_error");
  assert.equal(mapMediaError({ code: 3 }).kind, "decode_error");
  assert.equal(mapMediaError({ code: 4 }).kind, "source_not_supported");
  assert.equal(mapMediaError(null).kind, "none");
  assert.match(mapMediaError({ code: 3 }).message, /无法解码/);
});

test("compatibilityHint distinguishes well-known and uncertain formats", () => {
  assert.match(compatibilityHint("mp4"), /通常兼容较好/);
  assert.match(compatibilityHint("webm"), /通常兼容较好/);
  assert.match(compatibilityHint("mkv"), /取决于浏览器/);
  assert.match(compatibilityHint("avi"), /取决于浏览器/);
});

test("pictureInPictureSupported is safe without a DOM", () => {
  assert.equal(pictureInPictureSupported(), false);
});
