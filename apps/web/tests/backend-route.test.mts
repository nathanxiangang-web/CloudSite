import assert from "node:assert/strict";
import test from "node:test";

import { backendPathFor } from "../src/lib/backend-route.ts";


test("backendPathFor preserves direct backend routes", () => {
  assert.equal(backendPathFor("/api/admin/setup/status"), "/api/admin/setup/status");
  assert.equal(backendPathFor("/d/file-id"), "/d/file-id");
  assert.equal(backendPathFor("/p/resource-id"), "/p/resource-id");
  assert.equal(backendPathFor("/office-files/cache/doc.docx"), "/office-files/cache/doc.docx");
});


test("backendPathFor maps share helper routes", () => {
  assert.equal(backendPathFor("/s/abc123/verify"), "/api/public/shares/abc123/verify");
  assert.equal(backendPathFor("/s/abc123/content"), "/api/public/shares/abc123/content");
  assert.equal(backendPathFor("/s/abc123/d"), "/s/abc123/d");
  assert.equal(backendPathFor("/s/abc123/d/folder/file.txt"), "/s/abc123/d/folder/file.txt");
});


test("backendPathFor leaves frontend pages alone", () => {
  assert.equal(backendPathFor("/"), null);
  assert.equal(backendPathFor("/admin/setup"), null);
  assert.equal(backendPathFor("/s/abc123"), null);
  assert.equal(backendPathFor("/search"), null);
});
