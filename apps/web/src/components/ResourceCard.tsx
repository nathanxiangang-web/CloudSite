import { Download } from "lucide-react";
import Link from "next/link";
import { formatBytes, Resource } from "@/lib/api";
import { DownloadButton } from "./DownloadButton";
import { ResourceIcon } from "./ResourceIcon";

export function ResourceCard({ item }: { item: Resource }) {
  return <article className="resource-card"><Link href={`/resource/${item.id}`} className="resource-icon-link"><ResourceIcon item={item} size={30} /></Link><Link href={`/resource/${item.id}`} className="resource-copy"><strong title={item.name}>{item.name}</strong><span>{item.extension?.toUpperCase() || "文件"} · {formatBytes(item.size)}</span></Link><DownloadButton resourceId={item.id} className="icon-button" ariaLabel={`下载 ${item.name}`} compact><Download size={18} /></DownloadButton></article>;
}
