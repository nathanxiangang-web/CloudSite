import assert from "node:assert/strict";
import test from "node:test";

import { authRedirectTarget, safeNext } from "../src/lib/navigation.ts";


test("safeNext accepts only same-origin relative paths", () => {
  assert.equal(safeNext("/resource/r_123?from=search#preview"), "/resource/r_123?from=search#preview");
  assert.equal(safeNext("/"), "/");
  assert.equal(safeNext("https://evil.example"), "/");
  assert.equal(safeNext("//evil.example"), "/");
  assert.equal(safeNext("\\evil.example"), "/");
  assert.equal(safeNext("/\\evil.example"), "/");
  assert.equal(safeNext("/%5cevil.example"), "/");
  assert.equal(safeNext("/%2f%2fevil.example"), "/");
});


test("safeNext uses the supplied fallback for invalid input", () => {
  assert.equal(safeNext(null, "/login"), "/login");
  assert.equal(safeNext("account", "/login"), "/login");
});


test("anonymous login and register pages do not redirect-loop", () => {
  assert.equal(authRedirectTarget("/login", "", false, "AUTH_REQUIRED", null), null);
  assert.equal(authRedirectTarget("/register", "", false, "AUTH_REQUIRED", null), null);
  assert.equal(authRedirectTarget("/login", "", true, "", "//evil.example"), "/");
});


test("all share pages stay public without a CloudSite session", () => {
  assert.equal(authRedirectTarget("/s/AbC123", "", false, "AUTH_REQUIRED", null), null);
  assert.equal(authRedirectTarget("/s/AbC123/content", "", false, "AUTH_REQUIRED", null), null);
});


test("disabled session redirects with safe next and a limited reason", () => {
  const target = authRedirectTarget("/search", "?q=office", false, "USER_DISABLED", null);
  const location = new URL(target || "", "http://testserver");
  assert.equal(location.pathname, "/login");
  assert.equal(location.searchParams.get("next"), "/search?q=office");
  assert.equal(location.searchParams.get("reason"), "disabled");
});
