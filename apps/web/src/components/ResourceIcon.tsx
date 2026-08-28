import { AppWindow, Clapperboard, Disc3, File, FileArchive, FileText, Image, Presentation, Sheet } from "lucide-react";
import { Resource } from "@/lib/api";

type IconComponent = typeof File;

const extensionIcon: Record<string, { Icon: IconComponent; tone: string }> = {
  pdf: { Icon: FileText, tone: "pdf" },
  doc: { Icon: FileText, tone: "doc" },
  docx: { Icon: FileText, tone: "doc" },
  xls: { Icon: Sheet, tone: "xls" },
  xlsx: { Icon: Sheet, tone: "xls" },
  ppt: { Icon: Presentation, tone: "ppt" },
  pptx: { Icon: Presentation, tone: "ppt" },
  zip: { Icon: FileArchive, tone: "archive" },
  rar: { Icon: FileArchive, tone: "archive" },
  "7z": { Icon: FileArchive, tone: "archive" },
  iso: { Icon: Disc3, tone: "generic" },
};

export function resourceIconFor(item: Resource): { Icon: IconComponent; tone: string } {
  const ext = (item.extension || "").toLowerCase();
  if (ext in extensionIcon) return extensionIcon[ext];
  if (item.content_type === "image") return { Icon: Image, tone: "image" };
  if (item.content_type === "video") return { Icon: Clapperboard, tone: "video" };
  if (item.content_type === "software") return { Icon: AppWindow, tone: "software" };
  if (item.content_type === "document") return { Icon: FileText, tone: "document" };
  return { Icon: File, tone: "file" };
}

export function ResourceIcon({ item, size = 30 }: { item: Resource; size?: number }) {
  const { Icon, tone } = resourceIconFor(item);
  return <span className={`resource-icon type-${tone}`}><Icon size={size} /></span>;
}
