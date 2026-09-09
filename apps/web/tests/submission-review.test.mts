import assert from "node:assert/strict";
import test from "node:test";

import {
  buildReviewPayload,
  canPublishSubmission,
  defaultReviewAction,
  isPublishReady,
  publishedResultHref,
} from "../src/lib/submission-review.ts";


test("canPublishSubmission is true only for the approved state", () => {
  assert.equal(canPublishSubmission("approved"), true);
  assert.equal(canPublishSubmission("pending"), false);
  assert.equal(canPublishSubmission("rejected"), false);
  assert.equal(canPublishSubmission("published"), false);
});


test("defaultReviewAction maps each status to a permitted next action", () => {
  assert.equal(defaultReviewAction("pending"), "approve");
  assert.equal(defaultReviewAction("approved"), "publish");
  assert.equal(defaultReviewAction("rejected"), "reject");
  assert.equal(defaultReviewAction("published"), "approve");
});


test("isPublishReady requires a non-blank resource id only for publish", () => {
  assert.equal(isPublishReady("approve", ""), true);
  assert.equal(isPublishReady("reject", ""), true);
  assert.equal(isPublishReady("publish", ""), false);
  assert.equal(isPublishReady("publish", "   "), false);
  assert.equal(isPublishReady("publish", "r_123"), true);
  assert.equal(isPublishReady("publish", "  r_123  "), true);
});


test("buildReviewPayload sends resource_id only for publish and trims it", () => {
  const approve = buildReviewPayload("approve", "ok", "r_1");
  assert.deepEqual(approve, { action: "approve", admin_note: "ok" });

  const reject = buildReviewPayload("reject", "no", "r_1");
  assert.deepEqual(reject, { action: "reject", admin_note: "no" });

  const publish = buildReviewPayload("publish", "live", "  r_456  ");
  assert.deepEqual(publish, { action: "publish", admin_note: "live", resource_id: "r_456" });
});


test("publishedResultHref exposes a link only for published rows with a bound id", () => {
  assert.equal(publishedResultHref("published", "r_abc"), "/resource/r_abc");
  assert.equal(publishedResultHref("published", "  r_abc  "), "/resource/r_abc");
  assert.equal(publishedResultHref("approved", "r_abc"), null);
  assert.equal(publishedResultHref("rejected", "r_abc"), null);
  assert.equal(publishedResultHref("pending", "r_abc"), null);
  assert.equal(publishedResultHref("published", null), null);
  assert.equal(publishedResultHref("published", undefined), null);
  assert.equal(publishedResultHref("published", ""), null);
  assert.equal(publishedResultHref("published", "   "), null);
});


test("publishedResultHref encodes unsafe characters in the bound resource id", () => {
  assert.equal(publishedResultHref("published", "r a/b"), "/resource/r%20a%2Fb");
});
