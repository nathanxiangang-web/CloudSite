"use client";

import { Clapperboard, FileText, Home, Image, PanelsTopLeft } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSite } from "@/lib/site";
import { StorageInfoCard } from "./StorageInfoCard";

export const PUBLIC_NAV_ITEMS = [
  ["/", "首页", Home],
  ["/resources/software", "软件", PanelsTopLeft],
  ["/resources/image", "图库", Image],
  ["/resources/video", "视频", Clapperboard],
  ["/resources/document", "教程", FileText],
] as const;

// 0 张图片隐藏图库、0 篇教程隐藏教程入口；counts 未加载则保持显示（安全降级）
export function useVisibleNavItems() {
  const site = useSite();
  const counts = site.content_counts;
  if (counts) {
    return PUBLIC_NAV_ITEMS.filter(([href]) => {
      if (href === "/resources/image" && (counts.image ?? 0) === 0) return false;
      if (href === "/resources/document" && (counts.document ?? 0) === 0) return false;
      return true;
    });
  }
  return PUBLIC_NAV_ITEMS;
}

export function MobilePrimaryNavigation() {
  const pathname = usePathname();
  const items = useVisibleNavItems();
  return <section className="mobile-primary-navigation" aria-label="移动端资源导航">
    <nav className="mobile-primary-nav">
      {items.map(([href, label, Icon]) => <Link key={href} href={href} className={pathname === href ? "active" : ""} aria-current={pathname === href ? "page" : undefined}><Icon /><span>{label}</span></Link>)}
    </nav>
    <StorageInfoCard />
  </section>;
}
