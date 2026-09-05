"use client";

import { Clock3, Search, Upload } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Brand } from "./Brand";
import { StorageInfoCard } from "./StorageInfoCard";
import { AuthMenu } from "./AuthMenu";
import { ThemeToggle } from "./ThemeToggle";
import { NotificationBell } from "./NotificationBell";
import { MobilePrimaryNavigation, useVisibleNavItems } from "./PublicNavigation";

const TOPBAR_NAV = [
  ["/", "首页"],
  ["/resources/software", "资源库"],
  ["/collections", "精选"],
  ["/resources/file", "最近更新"],
  ["/about", "使用指南"],
] as const;

function TopbarActions() {
  return <div className="topbar-actions">
    <ThemeToggle />
    <NotificationBell />
    <Link href="/search" className="topbar-icon" title="全局搜索" aria-label="全局搜索"><Search /></Link>
    <Link href="/submit" className="topbar-icon" title="资源投稿" aria-label="资源投稿"><Upload /></Link>
  </div>;
}

export function PublicShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const navItems = useVisibleNavItems();
  return <div className={`app-shell${pathname === "/" ? " home-shell" : ""}`}>
    <header className="public-topbar">
      <Brand />
      <nav className="topbar-nav" aria-label="主导航">
        {TOPBAR_NAV.map(([href, label]) => <Link key={href} href={href} className={pathname === href ? "active" : ""}>{label}</Link>)}
      </nav>
      <TopbarActions />
      <AuthMenu />
    </header>
    <aside className="sidebar">
      <nav>
        {navItems.slice(0, 1).map(([href, label, Icon]) => <Link key={href} href={href} className={pathname === href ? "active" : ""}><Icon size={18} />{label}</Link>)}
        <span className="nav-section-label">资源库</span>
        {navItems.slice(1).map(([href, label, Icon]) => <Link key={href} href={href} className={pathname === href ? "active" : ""}><Icon size={18} />{label}</Link>)}
        <Link href="/resources/file" className={pathname === "/resources/file" ? "active" : ""}><Clock3 size={18} />最近更新</Link>
      </nav>
      <StorageInfoCard />
    </aside>
    <main className="content">
      <header className="mobile-header"><Brand /><div className="mobile-header-right"><TopbarActions /><AuthMenu /></div></header>
      {pathname !== "/" && <MobilePrimaryNavigation />}
      <div className="public-content">{children}</div>
    </main>
  </div>;
}
