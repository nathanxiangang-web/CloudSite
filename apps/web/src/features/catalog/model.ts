export const CATALOG_CONTENT_TYPE_LABELS: Record<string, string> = {
  software: "软件",
  image: "图库",
  video: "视频",
  document: "教程",
  file: "文件",
};

export function buildCatalogSearchQuery(params: {
  q: string;
  page?: number;
  page_size?: number;
  content_type?: string;
  tag?: string;
  platform?: string;
}): string {
  const query = new URLSearchParams();
  query.set("q", params.q);
  if (params.page) query.set("page", String(params.page));
  if (params.page_size) query.set("page_size", String(params.page_size));
  if (params.content_type) query.set("type", params.content_type);
  if (params.tag) query.set("tag", params.tag);
  if (params.platform) query.set("platform", params.platform);
  return `/api/catalog/search?${query.toString()}`;
}

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

export function contentTypeLabel(contentType: string): string {
  return CATALOG_CONTENT_TYPE_LABELS[contentType] ?? "资源";
}

export const CATALOG_ASSET_KIND_LABELS: Record<import("./types").CatalogAssetKind, string> = {
  file: "文件",
  document: "文档",
  image: "图片",
  video: "视频",
  archive: "压缩包",
  other: "其他",
};

export const CATALOG_CHANNEL_LABELS: Record<string, string> = {
  stable: "稳定",
  beta: "测试",
  historical: "历史",
  unknown: "未知",
};

export function assetKindLabel(kind: import("./types").CatalogAssetKind): string {
  return CATALOG_ASSET_KIND_LABELS[kind] ?? "文件";
}

export function channelLabel(channel: string): string {
  return CATALOG_CHANNEL_LABELS[channel] ?? channel ?? "未知";
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

export function releaseIsPublished(
  release: { status: import("./types").CatalogStatus },
): boolean {
  return release.status === "published";
}

export function releaseIsRecommended(release: { is_recommended?: boolean }): boolean {
  return Boolean(release.is_recommended);
}

export function releaseIsHistorical(release: { channel?: string }): boolean {
  return release.channel === "historical";
}

export function assetDimensionLabel(
  value: string | null | undefined,
  fallback = "通用",
): string {
  if (!value || value === "unknown") return fallback;
  return value;
}

export function catalogAssetDownloadPath(entryId: string, assetId: string): string {
  return `/api/catalog/entries/${encodeURIComponent(entryId)}/assets/${encodeURIComponent(assetId)}/download`;
}
