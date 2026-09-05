"use client";

import { Activity, Bell, Boxes, ClipboardList, FolderKanban, Gauge, Globe2, LogOut, Settings, Share2, Users } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { Brand } from "./Brand";

const items = [
  ["/admin", "概览", Gauge],
  ["/admin/index", "内容索引", Boxes],
  ["/admin/collections", "精选合集", FolderKanban],
  ["/admin/shares", "分享管理", Share2],
  ["/admin/submissions", "投稿审核", ClipboardList],
  ["/admin/notifications", "通知管理", Bell],
  ["/admin/users", "用户管理", Users],
  ["/admin/diagnostics", "下载诊断", Activity],
  ["/admin/site", "网站设置", Globe2],
  ["/admin/system", "系统", Settings],
] as const;

type AuthState =
  | { status: "loading" }
  | { status: "authenticated" }
  | { status: "error" }
  | { status: "redirect"; to: string };

export function AdminShell({ title, children }: { title: string; children: React.ReactNode }) {
  const pathname = usePathname();
  const [auth, setAuth] = useState<AuthState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    fetch("/api/admin/auth/status")
      .then((response) => response.json())
      .then((data) => {
        if (cancelled) return;
        const mode = data.mode as string | undefined;
        // 三态路由：setup_required → /admin/setup, login_required → /admin/login, authenticated → 放行
        if (mode === "setup_required") {
          setAuth({ status: "redirect", to: "/admin/setup" });
        } else if (mode === "login_required" || (data.auth_required && !data.authenticated)) {
          setAuth({ status: "redirect", to: "/admin/login" });
        } else if (mode === "authenticated" || !data.auth_required || data.authenticated) {
          setAuth({ status: "authenticated" });
        } else {
          setAuth({ status: "redirect", to: "/admin/login" });
        }
      })
      .catch(() => {
        // M5: 失败关闭 — 无法确认认证状态时不展示后台
        if (!cancelled) setAuth({ status: "error" });
      });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (auth.status === "redirect") window.location.replace(auth.to);
  }, [auth]);

  async function logout() {
    await fetch("/api/admin/auth/logout", { method: "POST" });
    window.location.replace("/admin/login");
  }

  if (auth.status === "loading") {
    return <div className="admin-auth-loading">正在验证后台访问权限…</div>;
  }

  if (auth.status === "error") {
    return <div className="admin-auth-loading">
      <p>无法连接后台服务，无法确认访问权限。</p>
      <button className="primary" onClick={() => setAuth({ status: "loading" })}>重试</button>
      <a href="/" className="back-link">返回前台</a>
    </div>;
  }

  if (auth.status === "redirect") {
    return <div className="admin-auth-loading">正在跳转…</div>;
  }

  return <div className="admin-shell">
    <aside className="admin-sidebar"><Brand admin /><nav>{items.map(([href, label, Icon]) => <Link key={href} href={href} className={pathname === href ? "active" : ""}><Icon size={20} />{label}</Link>)}</nav><Link className="back-link" href="/">返回前台</Link></aside>
    <main className="admin-main"><header><h1>{title}</h1><button className="admin-logout" onClick={logout} title="退出后台"><LogOut size={17} />退出</button></header>{children}</main>
  </div>;
}
