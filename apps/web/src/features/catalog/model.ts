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
