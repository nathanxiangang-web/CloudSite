"use client";

import { Search, Upload } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Brand } from "./Brand";
import { AuthMenu } from "./AuthMenu";
import { ThemeToggle } from "./ThemeToggle";
import { NotificationBell } from "./NotificationBell";
import { MobilePrimaryNavigation } from "./PublicNavigation";
import { useSite } from "@/lib/site";
import { CLOUD_DOWNLOAD_HREF, CLOUD_DOWNLOAD_LABEL, mapLegacyBrowseToCloudDownload } from "@/lib/navigation";

const TOPBAR_NAV = [
  ["/", "\u9996\u9875"],
  ["/resources/software", "\u8d44\u6e90\u5e93"],
  ["/catalog", "\u76ee\u5f55"],
  ["/collections", "\u7cbe\u9009"],
  [CLOUD_DOWNLOAD_HREF, CLOUD_DOWNLOAD_LABEL],
] as const;

function TopbarActions() {
  return <div className="topbar-actions">
    <ThemeToggle />
    <NotificationBell />
    <Link href="/search" className="topbar-icon" title="\u5168\u5c40\u641c\u7d22" aria-label="\u5168\u5c40\u641c\u7d22"><Search /></Link>
    <Link href="/submit" className="topbar-icon" title="\u8d44\u6e90\u6295\u7a3f" aria-label="\u8d44\u6e90\u6295\u7a3f"><Upload /></Link>
  </div>;
}

export function PublicShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const site = useSite();
  const presentation = site.presentation;
  const topbarNav = presentation && presentation.enabled && presentation.navigation.length
    ? [...presentation.navigation]
        .sort((a, b) => a.sort_order - b.sort_order)
        .map((item) => mapLegacyBrowseToCloudDownload(item))
        .filter((item) => item.href !== "/about")
    : TOPBAR_NAV.map(([href, label]) => ({ href, label }));
  return <div className={`app-shell${pathname === "/" ? " home-shell" : ""}`}>
    <header className="public-topbar">
      <Brand />
      <nav className="topbar-nav" aria-label="\u4e3b\u5bfc\u822a">
        {topbarNav.map(({ href, label }) => <Link key={href} href={href} className={pathname === href ? "active" : ""}>{label}</Link>)}
      </nav>
      <TopbarActions />
      <AuthMenu />
    </header>
    <main className="content">
      <header className="mobile-header"><Brand /><div className="mobile-header-right"><TopbarActions /><AuthMenu /></div></header>
      {pathname !== "/" && <MobilePrimaryNavigation />}
      <div className="public-content">{children}</div>
    </main>
  </div>;
}
