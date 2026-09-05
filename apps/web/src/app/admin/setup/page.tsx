"use client";

import { KeyRound, LogIn } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";
import { Brand } from "@/components/Brand";

export default function AdminSetupPage() {
  const [baseUrl, setBaseUrl] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(true);
  const [token, setToken] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [ready, setReady] = useState(false);
  const [setupAvailable, setSetupAvailable] = useState(true);

  useEffect(() => {
    fetch("/api/admin/setup/status")
      .then((response) => response.json())
      .then((status) => {
        if (!status.setup_required) {
          window.location.replace("/admin/login");
          return;
        }
        setSetupAvailable(status.setup_available);
        setReady(true);
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
    const response = await fetch("/api/admin/setup/alist", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CloudSite-Setup-Token": token,
      },
      body: JSON.stringify({ base_url: baseUrl, username, password, remember_credentials: remember }),
    });
    // 立即清理敏感字段（不持久化到浏览器）
    setToken("");
    setPassword("");
    if (response.ok) {
      window.location.replace("/admin/login");
      return;
    }
    const body = await response.json().catch(() => ({}));
    const detail = body.detail;
    setError(typeof detail === "string" ? detail : typeof detail?.message === "string" ? detail.message : "初始化失败，请检查配置");
    setLoading(false);
  }

  return <main className="login-page">
    <section className="login-card">
      <Brand admin />
      <div className="login-icon"><KeyRound /></div>
      <h1>初始化站点</h1>
      <p>首次部署请填写 AList 连接配置和一次性初始化令牌完成站点初始化。</p>
      {!setupAvailable && <p className="form-error">服务器未配置初始化令牌（CLOUDSITE_SETUP_TOKEN），请联系运维人员在服务器环境变量中配置后重启服务。</p>}
      <form className="form-stack" onSubmit={submit}>
        <label>AList 地址<input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} placeholder="https://alist.example.com" required /></label>
        <label>AList 管理员用户名<input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" required /></label>
        <label>AList 管理员密码<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="new-password" required /></label>
        <label className="checkbox-label"><input type="checkbox" checked={remember} onChange={(event) => setRemember(event.target.checked)} /> 记住登录凭据</label>
        <label>一次性初始化令牌<input type="password" value={token} onChange={(event) => setToken(event.target.value)} autoComplete="off" required /></label>
        {error && <p className="form-error">{error}</p>}
        <button className="primary login-submit" disabled={loading || !ready || !setupAvailable}><LogIn />{loading ? "正在初始化…" : "完成初始化"}</button>
      </form>
      <a href="/">返回 CloudSite 前台</a>
    </section>
  </main>;
}
