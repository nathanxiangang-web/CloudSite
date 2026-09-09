import assert from "node:assert/strict";
import test from "node:test";

import {
  adminCatalogEntryPath,
  adminCatalogEntryPublishPath,
  buildAdminCatalogEntryUpdatePayload,
  buildAdminCatalogPublishPayload,
} from "../src/lib/catalog-admin-helpers.ts";


test("adminCatalogEntryPath targets the version-aware entry endpoint and encodes IDs", () => {
  assert.equal(adminCatalogEntryPath("ce_abc"), "/api/admin/catalog/entries/ce_abc");
  assert.equal(adminCatalogEntryPath("ce_a b/"), "/api/admin/catalog/entries/ce_a%20b%2F");
});


test("adminCatalogEntryPublishPath targets the dedicated publish action and encodes IDs", () => {
  assert.equal(adminCatalogEntryPublishPath("ce_1"), "/api/admin/catalog/entries/ce_1/publish");
  assert.equal(adminCatalogEntryPublishPath("ce_a b"), "/api/admin/catalog/entries/ce_a%20b/publish");
});


test("buildAdminCatalogEntryUpdatePayload always carries expected_revision from the loaded entry", () => {
  const payload = buildAdminCatalogEntryUpdatePayload(7, { title: "Ubuntu 22.04", status: "draft" });
  assert.equal(payload.expected_revision, 7);
  assert.equal(payload.title, "Ubuntu 22.04");
  assert.equal(payload.status, "draft");
});


test("buildAdminCatalogEntryUpdatePayload preserves cover_resource_id null and optional fields", () => {
  const payload = buildAdminCatalogEntryUpdatePayload(0, {
    content_type: "software",
    slug: "ubuntu",
    summary: "LTS",
    description: "desc",
    cover_resource_id: null,
    sort_order: 2,
  });
  assert.equal(payload.expected_revision, 0);
  assert.equal(payload.cover_resource_id, null);
  assert.equal(payload.sort_order, 2);
  assert.equal(payload.slug, "ubuntu");
});


test("buildAdminCatalogPublishPayload carries only expected_revision", () => {
  const payload = buildAdminCatalogPublishPayload(5);
  assert.deepEqual(payload, { expected_revision: 5 });
});


test("buildAdminCatalogPublishPayload reflects the exact loaded revision without mutation", () => {
  const revision = 13;
  const payload = buildAdminCatalogPublishPayload(revision);
  assert.equal(payload.expected_revision, revision);
  assert.equal(payload.expected_revision, 13);
});
