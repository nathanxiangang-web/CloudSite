import { BookOpen, FolderTree } from "lucide-react";
import Link from "next/link";
import styles from "../styles/public-redesign.module.css";

export function LibraryTabs({
  active,
  contentType = "software",
}: {
  active: "catalog" | "files";
  contentType?: string;
}) {
  const fileHref = `/resources/${encodeURIComponent(contentType || "software")}`;
  return (
    <nav className={styles.libraryTabs} aria-label="资源库内容视图">
      <Link
        href="/catalog"
        className={active === "catalog" ? styles.libraryTabActive : styles.libraryTab}
      >
        <BookOpen size={16} />
        <span>
          <strong>资源条目</strong>
          <small>整理后的版本与下载资源</small>
        </span>
      </Link>
      <Link
        href={fileHref}
        className={active === "files" ? styles.libraryTabActive : styles.libraryTab}
      >
        <FolderTree size={16} />
        <span>
          <strong>文件与目录</strong>
          <small>CloudSite 索引中的对象</small>
        </span>
      </Link>
    </nav>
  );
}
