export type Resource = {
  id: string;
  name: string;
  parent_id: string | null;
  parent?: { id: string; name: string };
  content_type: string;
  extension: string;
  mime_type: string;
  size: number;
  modified_at: string | null;
  thumbnail: string;
};

export type PreviewCapability = {
  preview_type: "image" | "video" | "pdf" | "office" | "text" | "markdown" | "none";
  can_preview: boolean;
  preview_mode: "direct" | "office" | "text" | "none";
  reason: string;
  gateway_url: string;
  can_download: boolean;
};

export type Folder = {
  id: string;
  name: string;
  path?: string;
  parent_id: string | null;
  depth: number;
  content_type: string;
  root_mapping_id?: number | null;
  child_folder_count: number;
  resource_count: number;
  modified_at: string | null;
};

export type SearchResult = {
  id: string;
  object_type: "resource" | "folder";
  name: string;
  content_type: string;
  extension: string;
  size: number | null;
  modified_at: string | null;
  parent: { id: string; name: string } | null;
  breadcrumbs: Array<{ id: string; name: string }>;
  thumbnail: string;
  child_folder_count: number;
  resource_count: number;
  match_type: "exact" | "prefix" | "name" | "metadata";
};

export type SearchResponse = {
  query: string;
  filters: { type: string | null; object_type: string; sort: string };
  items: SearchResult[];
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
};

export type Collection = {
  id: number;
  name: string;
  description: string;
  cover: string;
  status: "active" | "hidden";
  visible_on_home: boolean;
  sort_order: number;
  item_count: number;
  items?: Resource[];
  created_at: string;
  updated_at: string;
};

export type Share = {
  token: string;
  object_type: "resource" | "folder" | "collection";
  object_id: string;
  title: string;
  enabled: boolean;
  expires_at: string | null;
  access_count: number;
  last_accessed_at: string | null;
  expired?: boolean;
  target_name?: string | null;
  created_at: string;
  updated_at: string;
};

export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...options,
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...options?.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = body.detail;
    const message = typeof detail === "string"
      ? detail
      : typeof detail?.message === "string"
        ? `${detail.code ? `[${detail.code}] ` : ""}${detail.message}`
        : "请求失败，请稍后重试";
    throw new Error(message);
  }
  return response.json();
}

export type StorageInfo = {
  primary: string;
  drives: string[];
};

export function formatBytes(value: number): string {
  if (!value) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  return `${(value / 1024 ** index).toFixed(index > 1 ? 1 : 0)} ${units[index]}`;
}
