"use client";

import { Clock3 } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Brand } from "./Brand";
import { StorageInfoCard } from "./StorageInfoCard";
import { AuthMenu } from "./AuthMenu";
import { MobilePrimaryNavigation, PUBLIC_NAV_ITEMS } from "./PublicNavigation";

export function PublicShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  return <div className={`app-shell${pathname === "/" ? " home-shell" : ""}`}>
    <aside className="sidebar">
      <Brand />
      <nav>
        {PUBLIC_NAV_ITEMS.slice(0, 1).map(([href, label, Icon]) => <Link key={href} href={href} className={pathname === href ? "active" : ""}><Icon size={18} />{label}</Link>)}
        <span className="nav-section-label">资源库</span>
        {PUBLIC_NAV_ITEMS.slice(1).map(([href, label, Icon]) => <Link key={href} href={href} className={pathname === href ? "active" : ""}><Icon size={18} />{label}</Link>)}
        <Link href="/resources/file" className={pathname === "/resources/file" ? "active" : ""}><Clock3 size={18} />最近更新</Link>
      </nav>
      <StorageInfoCard />
    </aside>
    <main className="content">
      <header className="public-topbar"><AuthMenu /></header>
      <header className="mobile-header"><Brand /><AuthMenu /></header>
      {pathname !== "/" && <MobilePrimaryNavigation />}
      <div className="public-content">{children}</div>
    </main>
  </div>;
}
