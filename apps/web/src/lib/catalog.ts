export type CatalogStatus = "draft" | "published" | "archived" | "disabled";
export type CatalogAssetKind = "file" | "document" | "image" | "video" | "archive" | "other";
export type CatalogAvailability = "available" | "unavailable";

export type CatalogTag = {
  tag_id: string;
  slug: string;
  display_name: string;
};

export type CatalogLocationResource = {
  id: string;
  name: string;
  extension: string;
  size: number;
  content_type: string;
} | null;

export type CatalogLocation = {
  location_id: string;
  resource_id: string;
  root_mapping_id: number | null;
  label: string;
  is_primary: boolean;
  status: "active" | "disabled";
  availability: CatalogAvailability;
  download_url: string;
  resource: CatalogLocationResource;
};

export type CatalogAssetSummary = {
  asset_id: string;
  slug: string;
  display_name: string;
  platform: string;
  kind: CatalogAssetKind;
  size: number | null;
  status: "active" | "disabled";
  availability: CatalogAvailability;
  location_count: number;
};

export type CatalogAssetDetail = CatalogAssetSummary & {
  checksum: string | null;
  checksum_algorithm: string | null;
  locations: CatalogLocation[];
};

export type CatalogReleaseSummary = {
  release_id: string;
  slug: string;
  title: string;
  status: CatalogStatus;
  published_at: string | null;
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

export type CatalogEntryDetail = CatalogEntrySummary & {
  description: string;
  releases: CatalogReleaseSummary[];
  relations: CatalogRelation[];
};

export type CatalogPage<T> = {
  items: T[];
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
};

export const CATALOG_CONTENT_TYPE_LABELS: Record<string, string> = {
  software: "软件",
  image: "图库",
  video: "视频",
  document: "教程",
  file: "文件",
};

export const CATALOG_ASSET_KIND_LABELS: Record<CatalogAssetKind, string> = {
  file: "文件",
  document: "文档",
  image: "图片",
  video: "视频",
  archive: "压缩包",
  other: "其他",
};

export const CATALOG_STATUS_LABELS: Record<CatalogStatus, string> = {
  draft: "草稿",
  published: "已发布",
  archived: "已归档",
  disabled: "已停用",
};

export function buildCatalogEntriesQuery(params: {
  page?: number;
  page_size?: number;
  content_type?: string;
  tag?: string;
} = {}): string {
  const query = new URLSearchParams();
  if (params.page) query.set("page", String(params.page));
  if (params.page_size) query.set("page_size", String(params.page_size));
  if (params.content_type) query.set("content_type", params.content_type);
  if (params.tag) query.set("tag", params.tag);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return `/api/catalog/entries${suffix}`;
}

export function catalogEntryHref(entryId: string): string {
  return `/catalog/${encodeURIComponent(entryId)}`;
}

export function catalogReleaseHref(releaseId: string): string {
  return `/catalog/releases/${encodeURIComponent(releaseId)}`;
}

export function catalogAssetHref(assetId: string): string {
  return `/catalog/assets/${encodeURIComponent(assetId)}`;
}

export function pickDownloadLocation(locations: CatalogLocation[]): CatalogLocation | null {
  const available = locations.filter((location) => location.availability === "available" && location.status === "active");
  if (available.length === 0) return null;
  const primary = available.find((location) => location.is_primary);
  return primary ?? available[0];
}

export function entryIsAvailable(entry: { availability: CatalogAvailability; status: CatalogStatus }): boolean {
  return entry.status === "published" && entry.availability === "available";
}

export function releaseIsPublished(release: { status: CatalogStatus }): boolean {
  return release.status === "published";
}

export function contentTypeLabel(contentType: string): string {
  return CATALOG_CONTENT_TYPE_LABELS[contentType] ?? "资源";
}

export function assetKindLabel(kind: CatalogAssetKind): string {
  return CATALOG_ASSET_KIND_LABELS[kind] ?? "文件";
}

export function statusLabel(status: CatalogStatus): string {
  return CATALOG_STATUS_LABELS[status] ?? status;
}

export function formatCatalogTimestamp(value: string | null | undefined): string {
  if (!value) return "未知";
  try {
    return new Intl.DateTimeFormat("zh-CN", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(new Date(value));
  } catch {
    return "未知";
  }
}
