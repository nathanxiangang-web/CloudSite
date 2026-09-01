export const SUBMISSION_EMAIL = "nathxo@outlook.com";
export const RESOURCE_TYPES = ["软件", "图片", "视频", "文档", "其他文件"] as const;

export type SubmissionInput = {
  resourceName: string;
  resourceType: string;
  description: string;
  sourceUrl: string;
  downloadUrl: string;
  copyrightNote: string;
  note: string;
  username: string;
};

export function isOptionalHttpUrl(value: string): boolean {
  if (!value.trim()) return true;
  try {
    const parsed = new URL(value.trim());
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch {
    return false;
  }
}

export function buildSubmission(input: SubmissionInput): { subject: string; body: string; mailto: string } {
  const subject = `[CloudSite资源投稿] ${input.resourceName.trim()}`;
  const body = [
    "CloudSite 资源投稿",
    "",
    `站内账号：${input.username}`,
    "",
    "资源名称：",
    input.resourceName.trim(),
    "",
    "资源类型：",
    input.resourceType,
    "",
    "资源简介：",
    input.description.trim(),
    "",
    "来源网址：",
    input.sourceUrl.trim(),
    "",
    "下载 / 网盘链接：",
    input.downloadUrl.trim(),
    "",
    "版权 / 授权说明：",
    input.copyrightNote.trim(),
    "",
    "备注：",
    input.note.trim(),
    "",
    "submitted_from：CloudSite 0.3.2",
  ].join("\n");
  const mailto = `mailto:${SUBMISSION_EMAIL}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
  return { subject, body, mailto };
}
