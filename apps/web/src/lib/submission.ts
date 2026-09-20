export const RESOURCE_TYPE_OPTIONS = [
  { value: "software", label: "软件" },
  { value: "image", label: "图库" },
  { value: "video", label: "视频" },
  { value: "document", label: "教程" },
  { value: "file", label: "其他文件" },
] as const;

export function isOptionalHttpUrl(value: string): boolean {
  if (!value.trim()) return true;
  try {
    const parsed = new URL(value.trim());
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch {
    return false;
  }
}
