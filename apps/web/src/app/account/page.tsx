"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CalendarDays, KeyRound, LogOut, Share2, ShieldCheck, UserRound } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { PublicShell } from "@/components/PublicShell";
import { api } from "@/lib/api";
import { AUTH_QUERY_KEY, useAuth } from "@/lib/auth";

export default function AccountPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const auth = useAuth();
  useEffect(() => { if (!auth.isLoading && !auth.data?.authenticated) router.replace("/login"); }, [auth.isLoading, auth.data?.authenticated, router]);
  const logout = useMutation({
    mutationFn: () => api<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),
    onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: AUTH_QUERY_KEY }); router.push("/login"); },
  });
  const user = auth.data?.user;
  return <PublicShell><div className="page account-page">
    {!user ? <div className="loading">正在读取账号…</div> : <>
      <section className="account-hero"><span className="account-avatar">{user.username.slice(0, 1).toUpperCase()}</span><div><p>CloudSite 账号</p><h1>{user.username}</h1><span className="status-pill active"><ShieldCheck />账号正常</span></div></section>
      <section className="account-grid">
        <article className="panel account-details"><h2><UserRound />账号信息</h2><dl>
          <div><dt>用户名</dt><dd>{user.username}</dd></div>
          <div><dt>账号状态</dt><dd>正常</dd></div>
          <div><dt>注册时间</dt><dd>{formatTime(user.created_at)}</dd></div>
          <div><dt>最近登录</dt><dd>{user.last_login_at ? formatTime(user.last_login_at) : "暂无记录"}</dd></div>
        </dl></article>
        <article className="panel account-actions"><h2><CalendarDays />账号操作</h2><p>管理当前账号创建的分享，或更新登录密码和退出账号。</p><Link className="button primary" href="/account/shares"><Share2 />我的分享</Link><Link className="button" href="/account/security"><KeyRound />修改密码</Link><button type="button" disabled={logout.isPending} onClick={() => logout.mutate()}><LogOut />{logout.isPending ? "正在退出…" : "退出登录"}</button></article>
      </section>
    </>}
  </div></PublicShell>;
}

function formatTime(value: string) { return new Date(value).toLocaleString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }); }
