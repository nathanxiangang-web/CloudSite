"use client";

import { LockKeyhole, LogIn } from "lucide-react";
import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { Brand } from "@/components/Brand";

export default function AdminLoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    fetch("/api/admin/auth/status")
      .then((response) => response.json())
      .then((status) => {
        const mode = status.mode as string | undefined;
        if (mode === "setup_required") {
          window.location.replace("/admin/setup");
        } else if (mode === "authenticated" || (!status.auth_required && status.authenticated)) {
          window.location.replace("/admin");
        } else {
          setReady(true);
        }
      })
      .catch(() => {
        setError("暂时无法连接后台服务，请检查网络后刷新重试");
        setReady(true);
      });
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError("");
    const response = await fetch("/api/admin/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    if (response.ok) {
      window.location.replace("/admin");
      return;
    }
    const body = await response.json().catch(() => ({}));
    const detail = body.detail;
    setError(typeof detail === "string" ? detail : typeof detail?.message === "string" ? detail.message : "登录失败，请检查账号信息");
    setLoading(false);
  }

  return <main className="login-page">
    <section className="login-card">
      <Brand admin />
      <div className="login-icon"><LockKeyhole /></div>
      <h1>进入管理后台</h1>
      <p>使用已保存 AList 服务对应的管理员账号验证身份。</p>
      <form className="form-stack" onSubmit={submit}>
        <label>用户名<input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" required /></label>
        <label>密码<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" required /></label>
        {error && <p className="form-error">{error}</p>}
        <button className="primary login-submit" disabled={loading || !ready}><LogIn />{loading ? "正在验证…" : "登录"}</button>
      </form>
      <Link href="/">返回 CloudSite 前台</Link>
    </section>
  </main>;
}
