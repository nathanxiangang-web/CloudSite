import { api } from "./api";
import type {
  CatalogAssetDetail,
  CatalogAssetKind,
  CatalogAssetSummary,
  CatalogEntryDetail,
  CatalogEntrySummary,
  CatalogLocation,
  CatalogPage,
  CatalogReleaseDetail,
  CatalogReleaseSummary,
  CatalogStatus,
  CatalogTag,
} from "./catalog";

export type AdminCatalogEntry = CatalogEntryDetail & {
  sort_order: number;
  created_at: string;
  published_at: string | null;
};

export type AdminCatalogRelease = CatalogReleaseDetail & {
  sort_order: number;
  created_at: string;
  published_at: string | null;
};

export type AdminCatalogAsset = CatalogAssetDetail & {
  sort_order: number;
  created_at: string;
  updated_at: string;
};

export type AdminCatalogLocation = CatalogLocation & {
  created_at: string;
  updated_at: string;
};

export type AdminCatalogRevision = {
  revision_id: string;
  target_type: "entry" | "release" | "asset" | "location" | "tag" | "relation";
  target_id: string;
  action: string;
  actor: string;
  created_at: string;
};

export type CatalogEntryInput = {
  content_type: string;
  slug?: string;
  title: string;
  summary?: string;
  description?: string;
  cover_resource_id?: string | null;
  status?: CatalogStatus;
  sort_order?: number;
};

export type CatalogReleaseInput = {
  slug: string;
  title: string;
  release_notes?: string;
  status?: CatalogStatus;
  sort_order?: number;
};

export type CatalogAssetInput = {
  slug: string;
  display_name: string;
  platform?: string;
  kind?: CatalogAssetKind;
  checksum?: string | null;
  checksum_algorithm?: string | null;
  size?: number | null;
  status?: "active" | "disabled";
  sort_order?: number;
};

export type CatalogLocationInput = {
  resource_id: string;
  label?: string;
  is_primary?: boolean;
  status?: "active" | "disabled";
};

export async function fetchCatalogEntries(params: {
  page?: number;
  page_size?: number;
  content_type?: string;
  tag?: string;
} = {}): Promise<CatalogPage<CatalogEntrySummary>> {
  const query = new URLSearchParams();
  if (params.page) query.set("page", String(params.page));
  if (params.page_size) query.set("page_size", String(params.page_size));
  if (params.content_type) query.set("content_type", params.content_type);
  if (params.tag) query.set("tag", params.tag);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return api<CatalogPage<CatalogEntrySummary>>(`/api/catalog/entries${suffix}`);
}

export async function fetchCatalogEntry(entryId: string): Promise<CatalogEntryDetail> {
  return api<CatalogEntryDetail>(`/api/catalog/entries/${encodeURIComponent(entryId)}`);
}

export async function fetchCatalogRelease(releaseId: string): Promise<CatalogReleaseDetail> {
  return api<CatalogReleaseDetail>(`/api/catalog/releases/${encodeURIComponent(releaseId)}`);
}

export async function fetchCatalogAsset(assetId: string): Promise<CatalogAssetDetail> {
  return api<CatalogAssetDetail>(`/api/catalog/assets/${encodeURIComponent(assetId)}`);
}

export async function fetchCatalogTags(): Promise<{ items: CatalogTag[] }> {
  return api<{ items: CatalogTag[] }>("/api/catalog/tags");
}

export async function fetchAdminCatalogEntries(): Promise<CatalogPage<AdminCatalogEntry>> {
  return api<CatalogPage<AdminCatalogEntry>>("/api/admin/catalog/entries");
}

export async function fetchAdminCatalogEntry(entryId: string): Promise<AdminCatalogEntry> {
  return api<AdminCatalogEntry>(`/api/admin/catalog/entries/${encodeURIComponent(entryId)}`);
}

export async function createAdminCatalogEntry(input: CatalogEntryInput): Promise<{ entry_id: string }> {
  return api<{ entry_id: string }>("/api/admin/catalog/entries", { method: "POST", body: JSON.stringify(input) });
}

export async function updateAdminCatalogEntry(entryId: string, input: Partial<CatalogEntryInput>): Promise<void> {
  return api<void>(`/api/admin/catalog/entries/${encodeURIComponent(entryId)}`, { method: "PATCH", body: JSON.stringify(input) });
}

export async function deleteAdminCatalogEntry(entryId: string): Promise<void> {
  return api<void>(`/api/admin/catalog/entries/${encodeURIComponent(entryId)}`, { method: "DELETE" });
}

export async function fetchAdminCatalogReleases(entryId: string): Promise<{ items: AdminCatalogRelease[] }> {
  return api<{ items: AdminCatalogRelease[] }>(`/api/admin/catalog/entries/${encodeURIComponent(entryId)}/releases`);
}

export async function createAdminCatalogRelease(entryId: string, input: CatalogReleaseInput): Promise<{ release_id: string }> {
  return api<{ release_id: string }>(`/api/admin/catalog/entries/${encodeURIComponent(entryId)}/releases`, { method: "POST", body: JSON.stringify(input) });
}

export async function updateAdminCatalogRelease(releaseId: string, input: Partial<CatalogReleaseInput>): Promise<void> {
  return api<void>(`/api/admin/catalog/releases/${encodeURIComponent(releaseId)}`, { method: "PATCH", body: JSON.stringify(input) });
}

export async function deleteAdminCatalogRelease(releaseId: string): Promise<void> {
  return api<void>(`/api/admin/catalog/releases/${encodeURIComponent(releaseId)}`, { method: "DELETE" });
}

export async function fetchAdminCatalogAssets(releaseId: string): Promise<{ items: AdminCatalogAsset[] }> {
  return api<{ items: AdminCatalogAsset[] }>(`/api/admin/catalog/releases/${encodeURIComponent(releaseId)}/assets`);
}

export async function createAdminCatalogAsset(releaseId: string, input: CatalogAssetInput): Promise<{ asset_id: string }> {
  return api<{ asset_id: string }>(`/api/admin/catalog/releases/${encodeURIComponent(releaseId)}/assets`, { method: "POST", body: JSON.stringify(input) });
}

export async function updateAdminCatalogAsset(assetId: string, input: Partial<CatalogAssetInput>): Promise<void> {
  return api<void>(`/api/admin/catalog/assets/${encodeURIComponent(assetId)}`, { method: "PATCH", body: JSON.stringify(input) });
}

export async function deleteAdminCatalogAsset(assetId: string): Promise<void> {
  return api<void>(`/api/admin/catalog/assets/${encodeURIComponent(assetId)}`, { method: "DELETE" });
}

export async function fetchAdminCatalogLocations(assetId: string): Promise<{ items: AdminCatalogLocation[] }> {
  return api<{ items: AdminCatalogLocation[] }>(`/api/admin/catalog/assets/${encodeURIComponent(assetId)}/locations`);
}

export async function attachAdminCatalogLocation(assetId: string, input: CatalogLocationInput): Promise<{ location_id: string }> {
  return api<{ location_id: string }>(`/api/admin/catalog/assets/${encodeURIComponent(assetId)}/locations`, { method: "POST", body: JSON.stringify(input) });
}

export async function updateAdminCatalogLocation(locationId: string, input: Partial<CatalogLocationInput>): Promise<void> {
  return api<void>(`/api/admin/catalog/locations/${encodeURIComponent(locationId)}`, { method: "PATCH", body: JSON.stringify(input) });
}

export async function detachAdminCatalogLocation(locationId: string): Promise<void> {
  return api<void>(`/api/admin/catalog/locations/${encodeURIComponent(locationId)}`, { method: "DELETE" });
}

export async function fetchAdminCatalogRevisions(params: { target_id?: string; page?: number } = {}): Promise<CatalogPage<AdminCatalogRevision>> {
  const query = new URLSearchParams();
  if (params.target_id) query.set("target_id", params.target_id);
  if (params.page) query.set("page", String(params.page));
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return api<CatalogPage<AdminCatalogRevision>>(`/api/admin/catalog/revisions${suffix}`);
}

export type {
  CatalogAssetDetail,
  CatalogAssetSummary,
  CatalogEntryDetail,
  CatalogEntrySummary,
  CatalogLocation,
  CatalogPage,
  CatalogReleaseDetail,
  CatalogReleaseSummary,
  CatalogStatus,
  CatalogTag,
};
