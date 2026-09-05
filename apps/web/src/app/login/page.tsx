"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { LogIn, UserRound } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { FormEvent, Suspense, useState } from "react";
import { Brand } from "@/components/Brand";
import { api } from "@/lib/api";
import { AUTH_QUERY_KEY, PublicUser } from "@/lib/auth";
import { safeNext } from "@/lib/navigation";

function LoginContent() {
  const queryClient = useQueryClient();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const params = useSearchParams();
  const reason = params.get("reason") || "";
  const login = useMutation({
    mutationFn: () => api<PublicUser>("/api/auth/login", { method: "POST", body: JSON.stringify({ username, password }) }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: AUTH_QUERY_KEY });
      const next = safeNext(params.get("next"));
      window.location.assign(next);
    },
  });
  const submit = (event: FormEvent) => { event.preventDefault(); login.mutate(); };

  return <main className="user-auth-page"><section className="user-auth-card">
    <Brand />
    <div className="user-auth-icon"><UserRound /></div>
    <h1>登录 CloudSite</h1>
    <p>使用你的 CloudSite 用户名和密码继续。</p>
    {reason === "disabled" && <p className="form-error">当前账号已停用，请联系管理员。</p>}
    <form className="form-stack" onSubmit={submit}>
      <label>用户名<input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" minLength={2} maxLength={16} required /></label>
      <label>密码<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" maxLength={72} required /></label>
      {login.error && <p className="form-error">{login.error.message}</p>}
      <button className="primary user-auth-submit" disabled={login.isPending}><LogIn />{login.isPending ? "正在登录…" : "登录"}</button>
    </form>
    <p className="user-auth-switch">还没有账号？<Link href="/register">注册</Link></p>
  </section></main>;
}

export default function LoginPage() {
  return <Suspense fallback={null}><LoginContent /></Suspense>;
}
