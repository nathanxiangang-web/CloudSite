"use client";

import { Activity, Boxes, FolderKanban, Gauge, Globe2, LogOut, Settings, Share2, Users } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { Brand } from "./Brand";

const items = [
  ["/admin", "概览", Gauge],
  ["/admin/index", "内容索引", Boxes],
  ["/admin/collections", "精选合集", FolderKanban],
  ["/admin/shares", "分享管理", Share2],
  ["/admin/users", "用户管理", Users],
  ["/admin/diagnostics", "下载诊断", Activity],
  ["/admin/site", "网站设置", Globe2],
  ["/admin/system", "系统", Settings],
] as const;

export function AdminShell({ title, children }: { title: string; children: React.ReactNode }) {
  const pathname = usePathname();
  const [auth, setAuth] = useState<{ auth_required: boolean; authenticated: boolean } | null>(null);

  useEffect(() => {
    fetch("/api/admin/auth/status")
      .then((response) => response.json())
      .then((status) => {
        setAuth(status);
        if (status.auth_required && !status.authenticated) window.location.replace("/admin/login");
      })
      .catch(() => setAuth({ auth_required: false, authenticated: true }));
  }, []);

  async function logout() {
    await fetch("/api/admin/auth/logout", { method: "POST" });
    window.location.replace("/admin/login");
  }

  if (!auth || (auth.auth_required && !auth.authenticated)) {
    return <div className="admin-auth-loading">正在验证后台访问权限…</div>;
  }

  return <div className="admin-shell">
    <aside className="admin-sidebar"><Brand admin /><nav>{items.map(([href, label, Icon]) => <Link key={href} href={href} className={pathname === href ? "active" : ""}><Icon size={20} />{label}</Link>)}</nav><Link className="back-link" href="/">返回前台</Link></aside>
    <main className="admin-main"><header><h1>{title}</h1>{auth.auth_required ? <button className="admin-logout" onClick={logout} title="退出后台"><LogOut size={17} />退出</button> : <span className="avatar">CS</span>}</header>{children}</main>
  </div>;
}
