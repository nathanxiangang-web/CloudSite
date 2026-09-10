"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Eye, History, Power, RefreshCw, Save } from "lucide-react";
import { FormEvent, useState } from "react";
import { AdminShell } from "@/components/AdminShell";
import { api } from "@/lib/api";
import { SITE_QUERY_KEY } from "@/lib/site";

type BlockType = "featured" | "recent" | "topic" | "category" | "continue";
type HomeBlock = { type: BlockType; enabled: boolean; sort_order: number; limit: number; title: string };
type NavItem = { label: string; href: string; sort_order: number };
type ThemeTokens = { accent_color: string; card_radius: number };
type PresentationConfig = {
  preset: string;
  theme_tokens: ThemeTokens;
  navigation: NavItem[];
  home_blocks: HomeBlock[];
  ordered_blocks?: HomeBlock[];
};
type Revision = { revision_id: number; revision: number; preset: string; summary: string; created_at: string };
type PresentationResponse = {
  enabled: boolean;
  config_revision: number;
  config: PresentationConfig;
  presets: Record<string, PresentationConfig>;
  revisions: Revision[];
};

const BLOCK_LABELS: Record<BlockType, string> = {
  featured: "精选合集",
  recent: "最新发布",
  topic: "推荐专题",
  category: "资源分类",
  continue: "继续使用",
};
const BLOCK_ORDER: BlockType[] = ["category", "featured", "recent", "topic", "continue"];

export default function PresentationPage() {
  const queryClient = useQueryClient();
  const presentation = useQuery({
    queryKey: ["presentation"],
    queryFn: () => api<PresentationResponse>("/api/admin/presentation"),
  });
  const [preset, setPreset] = useState<string>("software");
  const [theme, setTheme] = useState<ThemeTokens>({ accent_color: "#2563eb", card_radius: 12 });
  const [nav, setNav] = useState<NavItem[]>([]);
  const [blocks, setBlocks] = useState<HomeBlock[]>([]);
  const [summary, setSummary] = useState("");
  const [synced, setSynced] = useState<PresentationResponse | undefined>(presentation.data);

  if (presentation.data !== synced) {
    setSynced(presentation.data);
    if (presentation.data) {
      const cfg = presentation.data.config;
      setPreset(cfg.preset);
      setTheme(cfg.theme_tokens);
      setNav(cfg.navigation);
      setBlocks(cfg.home_blocks);
    }
  }

  const save = useMutation({
    mutationFn: () => api("/api/admin/presentation", {
      method: "PUT",
      body: JSON.stringify({ preset, theme_tokens: theme, navigation: nav, home_blocks: blocks, summary }),
    }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["presentation"] }),
        queryClient.invalidateQueries({ queryKey: SITE_QUERY_KEY }),
      ]);
      setSummary("");
    },
  });
  const applyPreset = useMutation({
    mutationFn: (id: string) => api("/api/admin/presentation/apply-preset", { method: "POST", body: JSON.stringify({ preset: id }) }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["presentation"] }),
        queryClient.invalidateQueries({ queryKey: SITE_QUERY_KEY }),
      ]);
    },
  });
  const rollback = useMutation({
    mutationFn: (revisionId: number) => api("/api/admin/presentation/rollback", { method: "POST", body: JSON.stringify({ revision_id: revisionId }) }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["presentation"] }),
        queryClient.invalidateQueries({ queryKey: SITE_QUERY_KEY }),
      ]);
    },
  });
  const toggle = useMutation({
    mutationFn: (enabled: boolean) => api("/api/admin/presentation/toggle", { method: "PUT", body: JSON.stringify({ enabled }) }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["presentation"] }),
        queryClient.invalidateQueries({ queryKey: SITE_QUERY_KEY }),
      ]);
    },
  });

  function moveBlock(index: number, dir: -1 | 1) {
    const next = [...blocks];
    const target = index + dir;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    setBlocks(next.map((b, i) => ({ ...b, sort_order: i })));
  }
  function moveNav(index: number, dir: -1 | 1) {
    const next = [...nav];
    const target = index + dir;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    setNav(next.map((n, i) => ({ ...n, sort_order: i })));
  }
  function applyPresetLocal(id: string) {
    const cfg = presentation.data?.presets[id];
    if (!cfg) return;
    setPreset(id);
    setTheme(cfg.theme_tokens);
    setNav(cfg.navigation);
    setBlocks(cfg.home_blocks);
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  const enabled = presentation.data?.enabled ?? false;
  const orderedPreview = [...blocks].filter((b) => b.enabled).sort((a, b) => a.sort_order - b.sort_order);

  return <AdminShell title="站点呈现"><div className="admin-page">
    <section className="panel">
      <h2>启停与预设</h2>
      <p className="panel-intro">切换软件站/教程站预设无需改源码；停用后首页回退到默认区块顺序，旧默认主题仍可恢复。</p>
      <div className="form-actions">
        <button type="button" className={enabled ? "primary" : ""} disabled={toggle.isPending} onClick={() => toggle.mutate(!enabled)}>
          <Power />{enabled ? "已启用（点击停用）" : "已停用（点击启用）"}
        </button>
      </div>
      <div className="form-actions" style={{ marginTop: 12 }}>
        <button type="button" disabled={applyPreset.isPending} onClick={() => applyPreset.mutate("software")}>应用软件站预设</button>
        <button type="button" disabled={applyPreset.isPending} onClick={() => applyPreset.mutate("tutorial")}>应用教程站预设</button>
      </div>
      {applyPreset.error && <p className="form-error">{applyPreset.error.message}</p>}
      {toggle.error && <p className="form-error">{toggle.error.message}</p>}
    </section>

    <section className="panel">
      <h2>主题与导航</h2>
      <form className="form-stack" onSubmit={submit}>
        <label>预设标识
          <select value={preset} onChange={(event) => { const id = event.target.value; setPreset(id); if (id !== "custom") applyPresetLocal(id); }}>
            <option value="software">软件站</option>
            <option value="tutorial">教程站</option>
            <option value="custom">自定义</option>
          </select>
        </label>
        <label>主题色<input type="color" value={theme.accent_color} onChange={(event) => setTheme({ ...theme, accent_color: event.target.value })} /></label>
        <label>卡片圆角<input type="number" min={0} max={32} value={theme.card_radius} onChange={(event) => setTheme({ ...theme, card_radius: Number(event.target.value) })} /></label>

        <h3 style={{ marginTop: 16 }}>导航项</h3>
        {nav.map((item, i) => (
          <div key={i} className="form-row" style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <input value={item.label} onChange={(event) => setNav(nav.map((n, j) => j === i ? { ...n, label: event.target.value } : n))} placeholder="名称" style={{ flex: 1 }} />
            <input value={item.href} onChange={(event) => setNav(nav.map((n, j) => j === i ? { ...n, href: event.target.value } : n))} placeholder="链接" style={{ flex: 1 }} />
            <button type="button" onClick={() => moveNav(i, -1)} disabled={i === 0}><ArrowUp size={15} /></button>
            <button type="button" onClick={() => moveNav(i, 1)} disabled={i === nav.length - 1}><ArrowDown size={15} /></button>
          </div>
        ))}

        <h3 style={{ marginTop: 16 }}>首页区块</h3>
        {blocks.map((block, i) => (
          <div key={i} className="form-row" style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <label className="checkbox" style={{ flex: "0 0 auto" }}>
              <input type="checkbox" checked={block.enabled} onChange={(event) => setBlocks(blocks.map((b, j) => j === i ? { ...b, enabled: event.target.checked } : b))} />
              {BLOCK_LABELS[block.type]}
            </label>
            <input value={block.title} onChange={(event) => setBlocks(blocks.map((b, j) => j === i ? { ...b, title: event.target.value } : b))} placeholder="标题" style={{ flex: 1, minWidth: 120 }} />
            <label style={{ flex: "0 0 auto" }}>数量<input type="number" min={1} max={24} value={block.limit} onChange={(event) => setBlocks(blocks.map((b, j) => j === i ? { ...b, limit: Number(event.target.value) } : b))} style={{ width: 70 }} /></label>
            <button type="button" onClick={() => moveBlock(i, -1)} disabled={i === 0}><ArrowUp size={15} /></button>
            <button type="button" onClick={() => moveBlock(i, 1)} disabled={i === blocks.length - 1}><ArrowDown size={15} /></button>
          </div>
        ))}

        <label>修改摘要<input value={summary} onChange={(event) => setSummary(event.target.value)} placeholder="可选，记录本次变更" /></label>
        <div className="form-actions">
          <button className="primary" disabled={save.isPending}><Save />{save.isPending ? "正在发布..." : "发布配置"}</button>
        </div>
        {save.isSuccess && <p className="form-success">已发布，首页将按新区块顺序渲染。</p>}
        {save.error && <p className="form-error">{save.error.message}</p>}
      </form>
    </section>

    <section className="panel">
      <h2><Eye size={18} /> 预览顺序</h2>
      <ol className="presentation-preview">
        {orderedPreview.length ? orderedPreview.map((b) => (
          <li key={b.type}>{b.title || BLOCK_LABELS[b.type]}<small>{BLOCK_LABELS[b.type]} · 最多 {b.limit} 项</small></li>
        )) : <li className="empty">暂无启用的区块。</li>}
      </ol>
    </section>

    <section className="panel">
      <h2><History size={18} /> 历史配置与回退</h2>
      <p className="panel-intro">每次发布保留上一配置可回退；回退生成新 revision，不覆盖历史。</p>
      {(presentation.data?.revisions ?? []).length ? (presentation.data?.revisions ?? []).map((rev) => (
        <div key={rev.revision_id} className="form-row" style={{ display: "flex", gap: 8, alignItems: "center", justifyContent: "space-between" }}>
          <span>revision {rev.revision} · {rev.preset}<small>{rev.summary || "—"} · {new Date(rev.created_at).toLocaleString("zh-CN")}</small></span>
          <button type="button" disabled={rollback.isPending} onClick={() => rollback.mutate(rev.revision_id)}><RefreshCw size={15} />回退</button>
        </div>
      )) : <p className="empty">暂无历史配置。</p>}
      {rollback.error && <p className="form-error">{rollback.error.message}</p>}
    </section>
  </div></AdminShell>;
}
