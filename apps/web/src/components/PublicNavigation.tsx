"use client";

import { Home, LayoutGrid, Sparkles, UserRound } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

const MOBILE_NAV_ITEMS = [
  ["/", "\u9996\u9875", Home],
  ["/resources/software", "\u8d44\u6e90", LayoutGrid],
  ["/collections", "\u7cbe\u9009", Sparkles],
  ["/account", "\u6211\u7684", UserRound],
] as const;

export function MobilePrimaryNavigation() {
  const pathname = usePathname();
  return <nav className="mobile-bottom-nav" aria-label="\u79fb\u52a8\u7aef\u5bfc\u822a">
    {MOBILE_NAV_ITEMS.map(([href, label, Icon]) => {
      const active = pathname === href || (href !== "/" && pathname.startsWith(href));
      return <Link key={href} href={href} className={active ? "active" : ""} aria-current={active ? "page" : undefined}><Icon /><span>{label}</span></Link>;
    })}
  </nav>;
}
