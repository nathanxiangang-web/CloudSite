"use client";

import { Clapperboard, FileText, Home, Image, PanelsTopLeft } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { StorageInfoCard } from "./StorageInfoCard";

export const PUBLIC_NAV_ITEMS = [
  ["/", "首页", Home],
  ["/resources/software", "软件", PanelsTopLeft],
  ["/resources/image", "图片", Image],
  ["/resources/video", "视频", Clapperboard],
  ["/resources/document", "文档", FileText],
] as const;

export function MobilePrimaryNavigation() {
  const pathname = usePathname();
  return <section className="mobile-primary-navigation" aria-label="移动端资源导航">
    <nav className="mobile-primary-nav">
      {PUBLIC_NAV_ITEMS.map(([href, label, Icon]) => <Link key={href} href={href} className={pathname === href ? "active" : ""} aria-current={pathname === href ? "page" : undefined}><Icon /><span>{label}</span></Link>)}
    </nav>
    <StorageInfoCard />
  </section>;
}
