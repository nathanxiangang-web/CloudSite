export type CatalogStatus = "draft" | "published" | "archived" | "disabled";
export type CatalogAvailability = "available" | "unavailable";

export type CatalogTag = {
  tag_id: string;
  slug: string;
  display_name: string;
};

export type CatalogReleaseSummary = {
  release_id: string;
  slug: string;
  title: string;
  channel: string;
  is_recommended: boolean;
  release_date: string | null;
  status: CatalogStatus;
  published_at: string | null;
};

export type CatalogEntrySummary = {
  entry_id: string;
  slug: string;
  title: string;
  content_type: string;
  summary: string;
  cover_resource_id: string | null;
  status: CatalogStatus;
  availability: CatalogAvailability;
  tags: CatalogTag[];
  updated_at: string;
};

export type CatalogPage<T> = {
  items: T[];
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
};

export type CatalogSearchMatchType = "exact" | "prefix" | "title" | "metadata" | "fts";

export type CatalogSearchItem = CatalogEntrySummary & {
  match_type: CatalogSearchMatchType;
  revision: number;
  sort_order: number;
  published_at: string | null;
  releases: CatalogReleaseSummary[];
};

export type CatalogSearchResponse = {
  query: string;
  filters: { content_type: string | null; tag: string | null; platform: string | null };
  items: CatalogSearchItem[];
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
  suggestion: string | null;
};

export type CatalogAssetKind = "file" | "document" | "image" | "video" | "archive" | "other";

export type CatalogAssetSummary = {
  asset_id: string;
  slug: string;
  display_name: string;
  platform: string;
  kind: CatalogAssetKind;
  architecture: string;
  package_type: string;
  language: string;
  build_label: string;
  size: number | null;
  status: "active" | "disabled";
  availability: CatalogAvailability;
  location_count: number;
};

export type CatalogReleaseDetail = CatalogReleaseSummary & {
  release_notes: string;
  assets: CatalogAssetSummary[];
};

export type CatalogRelation = {
  relation_id: string;
  to_entry_id: string;
  to_title: string;
  relation_type: string;
  note: string;
};

export type CatalogEntryDetail = CatalogEntrySummary & {
  description: string;
  releases: CatalogReleaseSummary[];
  relations: CatalogRelation[];
};
