import { Folder } from "lucide-react";
import Link from "next/link";
import type { Folder as FolderType } from "@/lib/api";

export function FolderCard({ item }: { item: FolderType }) {
  return <Link href={`/folder/${item.id}`} className="folder-card"><Folder /><span><strong>{item.name}</strong><small>{item.child_folder_count} 个子目录 · {item.resource_count} 个资源</small></span></Link>;
}
