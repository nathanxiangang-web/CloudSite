import assert from "node:assert/strict";
import test from "node:test";

import { buildSubmission, isOptionalHttpUrl, SUBMISSION_EMAIL } from "../src/lib/submission.ts";


test("submission mailto keeps recipient fixed and encodes Chinese and reserved characters", () => {
  const result = buildSubmission({
    resourceName: "工具 & 教程?",
    resourceType: "软件",
    description: "第一行\n第二行 = #1",
    sourceUrl: "https://example.com/a?x=1&y=2",
    downloadUrl: "https://example.com/d#part",
    copyrightNote: "允许转载",
    note: "备注",
    username: "JC",
  });
  const parsed = new URL(result.mailto);
  assert.equal(parsed.protocol, "mailto:");
  assert.equal(parsed.pathname, SUBMISSION_EMAIL);
  assert.equal(parsed.searchParams.get("subject"), "[CloudSite资源投稿] 工具 & 教程?");
  assert.match(parsed.searchParams.get("body") || "", /站内账号：JC/);
  assert.match(parsed.searchParams.get("body") || "", /第一行\n第二行 = #1/);
  assert.match(parsed.searchParams.get("body") || "", /submitted_from：CloudSite 0\.3\.1/);
});


test("submission URL fields accept only optional HTTP and HTTPS URLs", () => {
  assert.equal(isOptionalHttpUrl(""), true);
  assert.equal(isOptionalHttpUrl("https://example.com/file"), true);
  assert.equal(isOptionalHttpUrl("http://example.com"), true);
  assert.equal(isOptionalHttpUrl("javascript:alert(1)"), false);
  assert.equal(isOptionalHttpUrl("file:///etc/passwd"), false);
  assert.equal(isOptionalHttpUrl("not a url"), false);
});
