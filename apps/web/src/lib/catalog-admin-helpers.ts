import type { CatalogStatus } from "./catalog";

export type AdminCatalogEntryUpdateInput = {
  expected_revision: number;
  content_type?: string;
  slug?: string;
  title?: string;
  summary?: string;
  description?: string;
  cover_resource_id?: string | null;
  status?: CatalogStatus;
  sort_order?: number;
};

export type AdminCatalogEntryPublishInput = {
  expected_revision: number;
};

export function adminCatalogEntryPath(entryId: string): string {
  return `/api/admin/catalog/entries/${encodeURIComponent(entryId)}`;
}

export function adminCatalogEntryPublishPath(entryId: string): string {
  return `/api/admin/catalog/entries/${encodeURIComponent(entryId)}/publish`;
}

export function buildAdminCatalogEntryUpdatePayload(
  expectedRevision: number,
  fields: Omit<AdminCatalogEntryUpdateInput, "expected_revision">,
): AdminCatalogEntryUpdateInput {
  return { ...fields, expected_revision: expectedRevision };
}

export function buildAdminCatalogPublishPayload(expectedRevision: number): AdminCatalogEntryPublishInput {
  return { expected_revision: expectedRevision };
}
