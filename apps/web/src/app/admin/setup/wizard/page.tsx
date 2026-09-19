"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, Check, SkipForward } from "lucide-react";
import Link from "next/link";
import { FormEvent, useState } from "react";
import { Brand } from "@/components/Brand";
import { api } from "@/lib/api";

type WizardState = {
  current_step: string;
  completed_steps: string[];
  connect_done: boolean;
  scope_done: boolean;
  preset_done: boolean;
  samples_done: boolean;
  brand_done: boolean;
  preview_done: boolean;
  publish_done: boolean;
  wizard_completed: boolean;
  started_at: string;
  completed_at: string | null;
};

type RootMapping = { id: number; content_type: string; display_name: string; alist_path: string; enabled: boolean };

const STEPS = ["connect", "scope", "preset", "samples", "brand", "preview", "publish"] as const;
const STEP_LABELS: Record<string, string> = {
  connect: "连接 AList",
  scope: "选择范围",
  preset: "选择预设",
  samples: "样本整理",
  brand: "品牌设置",
  preview: "预览",
  publish: "发布",
};

export default function SetupWizardPage() {
  const queryClient = useQueryClient();
  const wizard = useQuery<WizardState>({
    queryKey: ["setup-wizard"],
    queryFn: () => api<WizardState>("/api/admin/setup/wizard"),
  });
  const rootMappings = useQuery<{ items: RootMapping[] }>({
    queryKey: ["wizard-root-mappings"],
    queryFn: () => api<{ items: RootMapping[] }>("/api/admin/root-mappings"),
    enabled: wizard.data?.current_step === "scope",
  });

  const [connectForm, setConnectForm] = useState({ base_url: "", username: "", password: "", remember_credentials: true, token: "" });
  const [scopeEnabled, setScopeEnabled] = useState<Record<number, boolean>>({});
  const [preset, setPreset] = useState<string>("software");
  const [brandForm, setBrandForm] = useState({ site_name: "", home_title: "", description: "", hero_subtitle: "", accent_color: "#2563eb", card_radius: 12 });
  const [error, setError] = useState("");

  const stepMutation = useMutation({
    mutationFn: ({ step, data, token }: { step: string; data: Record<string, unknown>; token?: string }) =>
      api("/api/admin/setup/wizard/step", {
        method: "POST",
        headers: token ? { "X-CloudSite-Setup-Token": token } : {},
        body: JSON.stringify({ step, data }),
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["setup-wizard"] });
    },
    onError: (err: Error) => setError(err.message),
  });

  const skipMutation = useMutation({
    mutationFn: () => api("/api/admin/setup/wizard/skip", { method: "POST" }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["setup-wizard"] });
    },
  });

  if (wizard.isLoading) {
    return <main className="login-page"><section className="login-card"><Brand admin /><p>正在加载向导…</p></section></main>;
  }
  if (wizard.error) {
    return <main className="login-page"><section className="login-card"><Brand admin /><p className="form-error">无法连接后台服务：{wizard.error.message}</p><button type="button" onClick={() => wizard.refetch()}>重试</button><Link href="/admin/setup">返回</Link></section></main>;
  }

  const state = wizard.data;
  if (!state) return null;
  if (state.wizard_completed) {
    return <main className="login-page"><section className="login-card"><Brand admin /><h1>建站完成</h1><p>向导已完成，现在可以登录管理后台。</p><Link href="/admin/login" className="primary">前往登录</Link></section></main>;
  }

  const currentStep = state.current_step as string;
  const currentIdx = STEPS.indexOf(currentStep as typeof STEPS[number]);

  function submitStep(step: string, data: Record<string, unknown>, token?: string) {
    setError("");
    stepMutation.mutate({ step, data, token });
  }

  function handleConnectSubmit(event: FormEvent) {
    event.preventDefault();
    submitStep("connect", { base_url: connectForm.base_url, username: connectForm.username, password: connectForm.password, remember_credentials: connectForm.remember_credentials }, connectForm.token);
    setConnectForm((f) => ({ ...f, token: "", password: "" }));
  }

  function handleScopeSubmit(event: FormEvent) {
    event.preventDefault();
    const mappings = (rootMappings.data?.items ?? []).map((m) => ({ id: m.id, enabled: scopeEnabled[m.id] ?? m.enabled }));
    submitStep("scope", { root_mappings: mappings });
  }

  function handlePresetSubmit(event: FormEvent) {
    event.preventDefault();
    submitStep("preset", { preset });
  }

  function handleBrandSubmit(event: FormEvent) {
    event.preventDefault();
    submitStep("brand", brandForm);
  }

  function goBack() {
    if (currentIdx > 0) {
      const prevStep = STEPS[currentIdx - 1];
      setError("");
      stepMutation.mutate({ step: prevStep, data: {} });
    }
  }

  return <main className="login-page">
    <section className="login-card wizard-card">
      <Brand admin />
      <h1>首次建站向导</h1>
      <ol className="wizard-progress">
        {STEPS.map((step, i) => (
          <li key={step} className={i === currentIdx ? "current" : i < currentIdx ? "done" : ""}>
            <span className="wizard-step-index">{i + 1}</span>
            <span className="wizard-step-label">{STEP_LABELS[step]}</span>
          </li>
        ))}
      </ol>

      {(error || skipMutation.error) && <p className="form-error">{error || skipMutation.error?.message}</p>}

      {currentStep === "connect" && (
        <form className="form-stack" onSubmit={handleConnectSubmit}>
          <h2>连接 AList</h2>
          <p className="panel-intro">填写 AList 服务器连接信息，向导会验证连接。</p>
          <label>AList 地址<input value={connectForm.base_url} onChange={(e) => setConnectForm({ ...connectForm, base_url: e.target.value })} placeholder="https://alist.example.com" required /></label>
          <label>用户名<input value={connectForm.username} onChange={(e) => setConnectForm({ ...connectForm, username: e.target.value })} required /></label>
          <label>密码<input type="password" value={connectForm.password} onChange={(e) => setConnectForm({ ...connectForm, password: e.target.value })} required /></label>
          <label className="checkbox-label"><input type="checkbox" checked={connectForm.remember_credentials} onChange={(e) => setConnectForm({ ...connectForm, remember_credentials: e.target.checked })} /> 记住凭据</label>
          {!state.connect_done && <label>初始化令牌<input type="password" value={connectForm.token} onChange={(e) => setConnectForm({ ...connectForm, token: e.target.value })} required /></label>}
          <button className="primary" disabled={stepMutation.isPending}><ArrowRight />下一步</button>
        </form>
      )}

      {currentStep === "scope" && (
        <form className="form-stack" onSubmit={handleScopeSubmit}>
          <h2>选择启用范围</h2>
          <p className="panel-intro">选择要在站点上启用的内容根目录。</p>
          {rootMappings.isLoading ? <p className="loading">正在读取内容根目录…</p> : rootMappings.error ? <div className="empty error-state">内容根目录加载失败：{rootMappings.error.message}<button type="button" onClick={() => rootMappings.refetch()}>重试</button></div> : <>
            {(rootMappings.data?.items ?? []).map((m) => (
              <label key={m.id} className="checkbox-label">
                <input type="checkbox" checked={scopeEnabled[m.id] ?? m.enabled} onChange={(e) => setScopeEnabled({ ...scopeEnabled, [m.id]: e.target.checked })} />
                {m.display_name} <small>{m.content_type} · {m.alist_path}</small>
              </label>
            ))}
            {(rootMappings.data?.items ?? []).length === 0 && <p className="empty">暂无内容根目录映射，可跳过此步。</p>}
          </>}
          <div className="form-actions">
            <button type="button" onClick={goBack}><ArrowLeft />上一步</button>
            <button className="primary" disabled={stepMutation.isPending || rootMappings.isLoading || Boolean(rootMappings.error)}><ArrowRight />下一步</button>
          </div>
        </form>
      )}

      {currentStep === "preset" && (
        <form className="form-stack" onSubmit={handlePresetSubmit}>
          <h2>选择站点预设</h2>
          <p className="panel-intro">选择预设可快速配置首页布局与导航，无需改源码。</p>
          <label>预设
            <select value={preset} onChange={(e) => setPreset(e.target.value)}>
              <option value="software">软件站</option>
              <option value="tutorial">教程站</option>
              <option value="custom">自定义</option>
            </select>
          </label>
          <div className="form-actions">
            <button type="button" onClick={goBack}><ArrowLeft />上一步</button>
            <button className="primary" disabled={stepMutation.isPending}><ArrowRight />下一步</button>
          </div>
        </form>
      )}

      {currentStep === "samples" && (
        <form className="form-stack" onSubmit={(e) => { e.preventDefault(); submitStep("samples", {}); }}>
          <h2>样本整理</h2>
          <p className="panel-intro">标记样本资源整理完成。此步仅记录状态，不做实际整理。</p>
          <div className="form-actions">
            <button type="button" onClick={goBack}><ArrowLeft />上一步</button>
            <button className="primary" disabled={stepMutation.isPending}><Check />标记完成</button>
          </div>
        </form>
      )}

      {currentStep === "brand" && (
        <form className="form-stack" onSubmit={handleBrandSubmit}>
          <h2>品牌设置</h2>
          <p className="panel-intro">设置站点名称、标题与主题色。</p>
          <label>站点名称<input value={brandForm.site_name} onChange={(e) => setBrandForm({ ...brandForm, site_name: e.target.value })} placeholder="CloudSite" /></label>
          <label>首页标题<input value={brandForm.home_title} onChange={(e) => setBrandForm({ ...brandForm, home_title: e.target.value })} /></label>
          <label>站点描述<input value={brandForm.description} onChange={(e) => setBrandForm({ ...brandForm, description: e.target.value })} /></label>
          <label>副标题<input value={brandForm.hero_subtitle} onChange={(e) => setBrandForm({ ...brandForm, hero_subtitle: e.target.value })} /></label>
          <label>主题色<input type="color" value={brandForm.accent_color} onChange={(e) => setBrandForm({ ...brandForm, accent_color: e.target.value })} /></label>
          <label>卡片圆角<input type="number" min={0} max={32} value={brandForm.card_radius} onChange={(e) => setBrandForm({ ...brandForm, card_radius: Number(e.target.value) })} /></label>
          <div className="form-actions">
            <button type="button" onClick={goBack}><ArrowLeft />上一步</button>
            <button className="primary" disabled={stepMutation.isPending}><ArrowRight />下一步</button>
          </div>
        </form>
      )}

      {currentStep === "preview" && (
        <form className="form-stack" onSubmit={(e) => { e.preventDefault(); submitStep("preview", {}); }}>
          <h2>预览配置</h2>
          <p className="panel-intro">确认当前配置效果，生成预览快照（不发布）。</p>
          <div className="presentation-preview">
            <p>站点名称：{brandForm.site_name || "CloudSite"}</p>
            <p>预设：{preset}</p>
            <p>主题色：<span style={{ display: "inline-block", width: 14, height: 14, background: brandForm.accent_color, borderRadius: 2, verticalAlign: "middle" }} /> {brandForm.accent_color}</p>
          </div>
          <div className="form-actions">
            <button type="button" onClick={goBack}><ArrowLeft />上一步</button>
            <button className="primary" disabled={stepMutation.isPending}><ArrowRight />下一步</button>
          </div>
        </form>
      )}

      {currentStep === "publish" && (
        <form className="form-stack" onSubmit={(e) => { e.preventDefault(); submitStep("publish", {}); }}>
          <h2>发布站点</h2>
          <p className="panel-intro">确认配置并完成建站。完成后可登录管理后台继续调整。</p>
          <div className="form-actions">
            <button type="button" onClick={goBack}><ArrowLeft />上一步</button>
            <button className="primary" disabled={stepMutation.isPending}><Check />完成建站</button>
          </div>
        </form>
      )}

      <div className="form-actions" style={{ marginTop: 16 }}>
        <button type="button" className="wizard-skip" disabled={skipMutation.isPending} onClick={() => skipMutation.mutate()}>
          <SkipForward size={15} />跳过向导
        </button>
        <Link href="/admin/setup">传统初始化</Link>
      </div>
    </section>
  </main>;
}
