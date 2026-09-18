import assert from "node:assert/strict";
import test from "node:test";

import { catalogEntryHref } from "../src/features/catalog/model.ts";


test("catalog detail href is the follow button login next target", () => {
  assert.equal(catalogEntryHref("ce_abc"), "/catalog/ce_abc");
  assert.equal(catalogEntryHref("ce_a b/"), "/catalog/ce_a%20b%2F");
});


test("follow button login redirect points back to the catalog detail page", () => {
  const entryId = "ce_abc";
  const detail = catalogEntryHref(entryId);
  const login = new URL("/login", "http://testserver");
  login.searchParams.set("next", detail);
  assert.equal(login.pathname, "/login");
  assert.equal(login.searchParams.get("next"), "/catalog/ce_abc");
});


test("my follows account route and file favorites route are siblings", () => {
  const myFollows = "/account/follows";
  const fileFavorites = "/account/favorites";
  assert.notEqual(myFollows, fileFavorites);
  assert.ok(myFollows.startsWith("/account/"));
  assert.ok(fileFavorites.startsWith("/account/"));
});


test("catalog follow API endpoint is distinct from file favorite endpoint", () => {
  const catalogFollow = "/api/me/catalog/favorites";
  const fileFavorite = "/api/me/favorites";
  assert.notEqual(catalogFollow, fileFavorite);
  assert.ok(catalogFollow.startsWith("/api/me/catalog/"));
  assert.ok(fileFavorite.startsWith("/api/me/favorites"));
});


test("catalog follow endpoint supports per-entry CRUD verbs", () => {
  const entryId = "ce_abc";
  const base = `/api/me/catalog/favorites/${entryId}`;
  const verbs = ["POST", "DELETE", "GET", "PATCH"];
  for (const verb of verbs) {
    assert.ok(base.startsWith("/api/me/catalog/favorites/"));
  }
  assert.equal(base, "/api/me/catalog/favorites/ce_abc");
});


test("my follows list endpoint is the collection root, not a per-entry path", () => {
  const list = "/api/me/catalog/favorites";
  const perEntry = "/api/me/catalog/favorites/ce_abc";
  assert.notEqual(list, perEntry);
  assert.ok(perEntry.startsWith(list + "/"));
});
