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
  draft?: {
    preset: string;
    site_name: string;
    home_title: string;
    description: string;
    hero_subtitle: string;
    accent_color: string;
    card_radius: number;
  };
  has_root_mappings?: boolean;
};

const STEPS = ["connect", "scope", "preset", "brand", "publish"] as const;
const STEP_LABELS: Record<string, string> = {
  connect: "连接 AList",
  scope: "选择范围",
  preset: "选择预设",
  brand: "品牌设置",
  publish: "发布",
};

const CONTENT_TYPES = [
  ["software", "软件"],
  ["image", "图库"],
  ["video", "视频"],
  ["document", "教程"],
  ["file", "普通文件"],
] as const;


export default function SetupWizardPage() {
  const queryClient = useQueryClient();
  const wizard = useQuery<WizardState>({
    queryKey: ["setup-wizard"],
    queryFn: () => api<WizardState>("/api/admin/setup/wizard"),
  });
  const [connectForm, setConnectForm] = useState({ base_url: "", username: "", password: "", token: "" });
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

  const backMutation = useMutation({
    mutationFn: () => api("/api/admin/setup/wizard/back", { method: "POST" }),
    onSuccess: async () => {
      setError("");
      await queryClient.invalidateQueries({ queryKey: ["setup-wizard"] });
    },
  });

  const skipMutation = useMutation({
    mutationFn: () => api("/api/admin/setup/wizard/skip", {
      method: "POST",
      headers: !wizard.data?.connect_done && connectForm.token
        ? { "X-CloudSite-Setup-Token": connectForm.token }
        : {},
    }),
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
    return <main className="login-page"><section className="login-card"><Brand admin /><h1>建站完成</h1><p>向导已完成，现在可以登录管理后台。</p><Link href="/admin/login?next=/admin/index" className="primary">登录并开始索引</Link></section></main>;
  }

  const currentStep = state.current_step as string;
  const currentIdx = STEPS.indexOf(currentStep as typeof STEPS[number]);

  function submitStep(step: string, data: Record<string, unknown>, token?: string) {
    setError("");
    stepMutation.mutate({ step, data, token });
  }

  function handleConnectSubmit(event: FormEvent) {
    event.preventDefault();
    submitStep("connect", { base_url: connectForm.base_url, username: connectForm.username, password: connectForm.password }, connectForm.token);
    setConnectForm((f) => ({ ...f, token: "", password: "" }));
  }

  function handleScopeSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const scopeState = wizard.data;
    if (!scopeState) return;
    if (scopeState.has_root_mappings) {
      submitStep("scope", { root_mappings: [] });
      return;
    }
    const form = new FormData(event.currentTarget);
    const path = String(form.get("alist_path") || "/").trim() || "/";
    submitStep("scope", {
      root_mappings: [{
        alist_path: path,
        display_name: String(form.get("display_name") || "").trim() || (path === "/" ? "全部内容" : path.split("/").filter(Boolean).at(-1) || "内容"),
        content_type: String(form.get("content_type") || "file"),
        enabled: true,
        sort_order: 0,
      }],
    });
  }

  function handlePresetSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    submitStep("preset", { preset: String(form.get("preset") || "software") });
  }

  function handleBrandSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    submitStep("brand", {
      site_name: String(form.get("site_name") || ""),
      home_title: String(form.get("home_title") || ""),
      description: String(form.get("description") || ""),
      hero_subtitle: String(form.get("hero_subtitle") || ""),
      accent_color: String(form.get("accent_color") || "#2563eb"),
      card_radius: Number(form.get("card_radius") || 12),
    });
  }

  function goBack() {
    if (currentIdx > 0) {
      setError("");
      backMutation.mutate();
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

      {(error || backMutation.error || skipMutation.error) && <p className="form-error">{error || backMutation.error?.message || skipMutation.error?.message}</p>}

      {currentStep === "connect" && (
        <form className="form-stack" onSubmit={handleConnectSubmit}>
          <h2>连接 AList</h2>
          <p className="panel-intro">填写 AList 服务器连接信息，向导会验证连接。</p>
          <label>AList 地址<input value={connectForm.base_url} onChange={(e) => setConnectForm({ ...connectForm, base_url: e.target.value })} placeholder="https://alist.example.com" required /></label>
          <label>用户名<input value={connectForm.username} onChange={(e) => setConnectForm({ ...connectForm, username: e.target.value })} required /></label>
          <label>密码<input type="password" value={connectForm.password} onChange={(e) => setConnectForm({ ...connectForm, password: e.target.value })} required /></label>
          {!state.connect_done && <label>初始化令牌<input type="password" value={connectForm.token} onChange={(e) => setConnectForm({ ...connectForm, token: e.target.value })} required /></label>}
          <button className="primary" disabled={stepMutation.isPending}><ArrowRight />下一步</button>
        </form>
      )}

      {currentStep === "scope" && (
        <form className="form-stack" onSubmit={handleScopeSubmit}>
          <h2>选择启用范围</h2>
          {state.has_root_mappings ? (
            <p className="panel-intro">已检测到根目录映射，本次向导保留现有配置。完成建站后可在系统设置中继续调整。</p>
          ) : (
            <>
              <p className="panel-intro">设置首次索引范围。默认使用整个 AList 根目录；复杂的多目录配置可在建站完成后继续调整。</p>
              <label>根目录路径<input name="alist_path" defaultValue="/" required /></label>
              <label>显示名称<input name="display_name" defaultValue="全部内容" /></label>
              <label>内容类型
                <select name="content_type" defaultValue="file">
                  {CONTENT_TYPES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select>
              </label>
            </>
          )}
          <div className="form-actions">
            <button type="button" disabled={backMutation.isPending || stepMutation.isPending} onClick={goBack}><ArrowLeft />上一步</button>
            <button className="primary" disabled={stepMutation.isPending}><ArrowRight />下一步</button>
          </div>
        </form>
      )}

      {currentStep === "preset" && (
        <form className="form-stack" onSubmit={handlePresetSubmit}>
          <h2>选择站点预设</h2>
          <p className="panel-intro">选择预设可快速配置首页布局与导航，无需改源码。</p>
          <label>预设
            <select name="preset" defaultValue={state.draft?.preset || "software"}>
              <option value="software">软件站</option>
              <option value="tutorial">教程站</option>
              <option value="custom">自定义</option>
            </select>
          </label>
          <div className="form-actions">
            <button type="button" disabled={backMutation.isPending || stepMutation.isPending} onClick={goBack}><ArrowLeft />上一步</button>
            <button className="primary" disabled={stepMutation.isPending}><ArrowRight />下一步</button>
          </div>
        </form>
      )}

      {currentStep === "brand" && (
        <form className="form-stack" onSubmit={handleBrandSubmit}>
          <h2>品牌设置</h2>
          <p className="panel-intro">设置站点名称、标题与主题色。</p>
          <label>站点名称<input name="site_name" defaultValue={state.draft?.site_name || ""} placeholder="CloudSite" /></label>
          <label>首页标题<input name="home_title" defaultValue={state.draft?.home_title || ""} /></label>
          <label>站点描述<input name="description" defaultValue={state.draft?.description || ""} /></label>
          <label>副标题<input name="hero_subtitle" defaultValue={state.draft?.hero_subtitle || ""} /></label>
          <label>主题色<input name="accent_color" type="color" defaultValue={state.draft?.accent_color || "#2563eb"} /></label>
          <label>卡片圆角<input name="card_radius" type="number" min={0} max={32} defaultValue={state.draft?.card_radius ?? 12} /></label>
          <div className="form-actions">
            <button type="button" disabled={backMutation.isPending || stepMutation.isPending} onClick={goBack}><ArrowLeft />上一步</button>
            <button className="primary" disabled={stepMutation.isPending}><ArrowRight />下一步</button>
          </div>
        </form>
      )}

      {currentStep === "publish" && (
        <form className="form-stack" onSubmit={(e) => { e.preventDefault(); submitStep("publish", {}); }}>
          <h2>发布站点</h2>
          <p className="panel-intro">确认配置并正式启用站点呈现。完成后可登录管理后台继续调整。</p>
          <div className="form-actions">
            <button type="button" disabled={backMutation.isPending || stepMutation.isPending} onClick={goBack}><ArrowLeft />上一步</button>
            <button className="primary" disabled={stepMutation.isPending}><Check />完成建站</button>
          </div>
        </form>
      )}

      <div className="form-actions" style={{ marginTop: 16 }}>
        <button type="button" className="wizard-skip" disabled={skipMutation.isPending || (!state.connect_done && !connectForm.token)} onClick={() => skipMutation.mutate()}>
          <SkipForward size={15} />跳过向导
        </button>
        <Link href="/admin/setup">传统初始化</Link>
      </div>
    </section>
  </main>;
}
