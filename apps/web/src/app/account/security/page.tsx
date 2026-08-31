"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CheckCircle2, KeyRound, Save } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import { PublicShell } from "@/components/PublicShell";
import { api } from "@/lib/api";
import { AUTH_QUERY_KEY, useAuth } from "@/lib/auth";

export default function AccountSecurityPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const auth = useAuth();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  useEffect(() => { if (!auth.isLoading && !auth.data?.authenticated) router.replace("/login"); }, [auth.isLoading, auth.data?.authenticated, router]);
  const change = useMutation({
    mutationFn: () => api<{ ok: boolean }>("/api/auth/change-password", { method: "POST", body: JSON.stringify({ current_password: currentPassword, new_password: newPassword, new_password_confirm: confirmPassword }) }),
    onSuccess: async () => { setCurrentPassword(""); setNewPassword(""); setConfirmPassword(""); await queryClient.invalidateQueries({ queryKey: AUTH_QUERY_KEY }); },
  });
  const submit = (event: FormEvent) => { event.preventDefault(); change.mutate(); };
  return <PublicShell><div className="page security-page">
    <Link className="account-back" href="/account"><ArrowLeft />返回我的账号</Link>
    <section className="panel security-card"><div className="security-heading"><span><KeyRound /></span><div><h1>修改密码</h1><p>更新后所有旧登录会话都会失效，本设备会自动创建新会话。</p></div></div>
      <form className="form-stack" onSubmit={submit}>
        <label>当前密码<input type="password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} autoComplete="current-password" maxLength={72} required /></label>
        <label>新密码<input type="password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} autoComplete="new-password" minLength={8} maxLength={72} required /><small>长度 8～72 位</small></label>
        <label>确认新密码<input type="password" value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} autoComplete="new-password" minLength={8} maxLength={72} required /></label>
        {change.isSuccess && <p className="form-success"><CheckCircle2 />密码已更新，旧会话已撤销</p>}
        {change.error && <p className="form-error">{change.error.message}</p>}
        <button className="primary" disabled={change.isPending}><Save />{change.isPending ? "正在保存…" : "保存新密码"}</button>
      </form>
    </section>
  </div></PublicShell>;
}
