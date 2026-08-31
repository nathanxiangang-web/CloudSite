"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { UserRoundPlus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import { Brand } from "@/components/Brand";
import { api } from "@/lib/api";
import { AUTH_QUERY_KEY, PublicUser, useAuth } from "@/lib/auth";

export default function RegisterPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const auth = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  useEffect(() => { if (auth.data?.authenticated) router.replace("/account"); }, [auth.data?.authenticated, router]);
  const register = useMutation({
    mutationFn: () => api<PublicUser>("/api/auth/register", { method: "POST", body: JSON.stringify({ username, password, password_confirm: passwordConfirm }) }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: AUTH_QUERY_KEY });
      router.push("/account");
    },
  });
  const submit = (event: FormEvent) => { event.preventDefault(); register.mutate(); };

  return <main className="user-auth-page"><section className="user-auth-card">
    <Brand />
    <div className="user-auth-icon"><UserRoundPlus /></div>
    <h1>创建账号</h1>
    <p>注册后会自动登录，公开资源仍可匿名访问。</p>
    <form className="form-stack" onSubmit={submit}>
      <label>用户名<input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" maxLength={32} pattern="[A-Za-z0-9_-]{3,32}" required /><small>3～32 位，仅允许字母、数字、下划线和短横线</small></label>
      <label>密码<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="new-password" minLength={8} maxLength={72} required /><small>密码长度 8～72 位</small></label>
      <label>确认密码<input type="password" value={passwordConfirm} onChange={(event) => setPasswordConfirm(event.target.value)} autoComplete="new-password" minLength={8} maxLength={72} required /></label>
      {register.error && <p className="form-error">{register.error.message}</p>}
      <button className="primary user-auth-submit" disabled={register.isPending}><UserRoundPlus />{register.isPending ? "正在创建…" : "创建账号"}</button>
    </form>
    <p className="user-auth-switch">已有账号？<Link href="/login">登录</Link></p>
  </section></main>;
}
