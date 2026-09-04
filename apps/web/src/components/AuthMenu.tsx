"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, Heart, KeyRound, LogIn, LogOut, PlayCircle, Share2, UserRound, UserRoundPlus } from "lucide-react";
import Link from "next/link";
import { api } from "@/lib/api";
import { AUTH_QUERY_KEY, useAuth } from "@/lib/auth";
import { useSite } from "@/lib/site";

export function AuthMenu() {
  const auth = useAuth();
  const site = useSite();
  const queryClient = useQueryClient();
  const logout = useMutation({
    mutationFn: () => api<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: AUTH_QUERY_KEY });
      window.location.assign("/login");
    },
  });

  if (auth.isLoading) return <span className="auth-menu-loading">正在读取账号…</span>;
  if (!auth.data?.authenticated || !auth.data.user) {
    return <nav className="auth-links" aria-label="账号入口">
      <Link href="/login"><LogIn />登录</Link>
      {site.registration_enabled && <Link className="primary" href="/register"><UserRoundPlus />注册</Link>}
    </nav>;
  }

  const user = auth.data.user;
  return <details className="auth-menu">
    <summary><span className="user-avatar">{user.username.slice(0, 1).toUpperCase()}</span><strong>{user.username}</strong><ChevronDown /></summary>
    <div className="auth-dropdown">
      <Link href="/account"><UserRound />我的账号</Link>
      <Link href="/account/favorites"><Heart />我的收藏</Link>
      <Link href="/account/playback"><PlayCircle />继续播放</Link>
      <Link href="/account/shares"><Share2 />我的分享</Link>
      <Link href="/account/security"><KeyRound />修改密码</Link>
      <button type="button" disabled={logout.isPending} onClick={() => logout.mutate()}><LogOut />{logout.isPending ? "正在退出…" : "退出登录"}</button>
    </div>
  </details>;
}
