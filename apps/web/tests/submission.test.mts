import assert from "node:assert/strict";
import test from "node:test";

import { isOptionalHttpUrl, RESOURCE_TYPE_OPTIONS } from "../src/lib/submission.ts";


test("submission URL fields accept only optional HTTP and HTTPS URLs", () => {
  assert.equal(isOptionalHttpUrl(""), true);
  assert.equal(isOptionalHttpUrl("https://example.com/file"), true);
  assert.equal(isOptionalHttpUrl("http://example.com"), true);
  assert.equal(isOptionalHttpUrl("https://"), false);
  assert.equal(isOptionalHttpUrl("javascript:alert(1)"), false);
  assert.equal(isOptionalHttpUrl("file:///etc/passwd"), false);
  assert.equal(isOptionalHttpUrl("not a url"), false);
});


test("submission resource types keep machine values separate from Chinese labels", () => {
  assert.deepEqual(
    RESOURCE_TYPE_OPTIONS.map((item) => item.value),
    ["software", "image", "video", "document", "file"],
  );
  assert.deepEqual(
    RESOURCE_TYPE_OPTIONS.map((item) => item.label),
    ["软件", "图库", "视频", "教程", "其他文件"],
  );
});
