import assert from "node:assert/strict";
import test from "node:test";

import { normalizeSearchQuery, SEARCH_QUERY_MAX_LENGTH } from "../src/lib/search-query.ts";


test("search query normalization matches the UI and API length boundary", () => {
  assert.equal(normalizeSearchQuery("  Office   2024  "), "Office 2024");
  assert.equal(normalizeSearchQuery("A".repeat(500)).length, SEARCH_QUERY_MAX_LENGTH);
});
