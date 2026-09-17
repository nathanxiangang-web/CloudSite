export type ParserCandidateStatus = "pending" | "running" | "completed" | "failed" | "cancelled";

export type ParserCandidateTask = {
  task_id: string;
  resource_id: string;
  input_fingerprint: string;
  parser_version: string;
  status: ParserCandidateStatus;
  retry_count: number;
  result_json: string | null;
  error_text: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
};

export const DEFAULT_PARSER_EVALUATION_CASES = [
  { resource_id: "eval_windows", name: "Cloud-App-1.2.3-windows-x64.zip", extension: "zip", expected: { platform: "windows", architecture: "x64", version: "1.2.3", package_form: "zip" } },
  { resource_id: "eval_hyphen", name: "Toolkit-v2.5-x86-64.tar.gz", extension: "gz", expected: { architecture: "x64", version: "2.5", package_form: "tar_gz" } },
  { resource_id: "eval_chinese", name: "网络教程-2026.09.10-zh.7z", extension: "7z", expected: { language: "zh", version: "2026.09.10", package_form: "7z" } },
  { resource_id: "eval_linux", name: "agent_3.4.0_linux_arm64.deb", extension: "deb", expected: { platform: "linux", architecture: "arm64", version: "3.4.0", package_form: "deb" } },
  { resource_id: "eval_unknown", name: "readme-final.bin", extension: "bin", expected: { platform: "unknown", architecture: "unknown", version: "unknown", package_form: "unknown" } },
] as const;

export function parserCandidateListPath(filters: { status?: string; resourceId?: string; limit?: number; offset?: number } = {}) {
  const query = new URLSearchParams();
  if (filters.status) query.set("status", filters.status);
  if (filters.resourceId) query.set("resource_id", filters.resourceId);
  if (filters.limit !== undefined) query.set("limit", String(filters.limit));
  if (filters.offset !== undefined) query.set("offset", String(filters.offset));
  const suffix = query.toString();
  return `/api/admin/parser-candidates${suffix ? `?${suffix}` : ""}`;
}

export function parserCandidateRetryPath(taskId: string) {
  return `/api/admin/parser-candidates/${encodeURIComponent(taskId)}/retry`;
}

export function parserCandidateStatusLabel(status: ParserCandidateStatus) {
  return { pending: "待处理", running: "处理中", completed: "已完成", failed: "失败", cancelled: "已取消" }[status];
}

export function parseCandidateResult(resultJson: string | null): Record<string, unknown> | null {
  if (!resultJson) return null;
  try {
    const value: unknown = JSON.parse(resultJson);
    return value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
  } catch {
    return null;
  }
}
