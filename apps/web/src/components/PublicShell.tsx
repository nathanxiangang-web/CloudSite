"use client";

import { Clapperboard, Clock3, FileText, Home, Image, PanelsTopLeft } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Brand } from "./Brand";
import { StorageInfoCard } from "./StorageInfoCard";
import { AuthMenu } from "./AuthMenu";

const items = [
  ["/", "首页", Home],
  ["/resources/software", "软件", PanelsTopLeft],
  ["/resources/image", "图片", Image],
  ["/resources/video", "视频", Clapperboard],
  ["/resources/document", "文档", FileText],
] as const;

export function PublicShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  return <div className={`app-shell${pathname === "/" ? " home-shell" : ""}`}>
    <aside className="sidebar">
      <Brand />
      <nav>
        {items.slice(0, 1).map(([href, label, Icon]) => <Link key={href} href={href} className={pathname === href ? "active" : ""}><Icon size={18} />{label}</Link>)}
        <span className="nav-section-label">资源库</span>
        {items.slice(1).map(([href, label, Icon]) => <Link key={href} href={href} className={pathname === href ? "active" : ""}><Icon size={18} />{label}</Link>)}
        <Link href="/resources/file" className={pathname === "/resources/file" ? "active" : ""}><Clock3 size={18} />最近更新</Link>
      </nav>
      <StorageInfoCard />
    </aside>
    <main className="content">
      <header className="public-topbar"><AuthMenu /></header>
      <div className="public-content">{children}</div>
    </main>
  </div>;
}
