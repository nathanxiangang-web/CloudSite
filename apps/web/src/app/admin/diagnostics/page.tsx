"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Clock3, Fingerprint, Search, XCircle } from "lucide-react";
import { useState } from "react";
import { AdminShell } from "@/components/AdminShell";
import { api, SearchResponse } from "@/lib/api";
import { SEARCH_QUERY_MAX_LENGTH } from "@/lib/search-query";

type Step = { name: string; status: "success" | "failed" | "skipped" | "cached"; duration_ms: number };
type Diagnostic = { id: number; resource_id: string; resource_name?: string; status: "success" | "failed"; failed_step: string; error_code: string | null; message: string; duration_ms: number; target_host: string; has_sign?: boolean; base_path?: string; steps?: Step[]; created_at: string };
type IdentityStats = { total: number; legacy_seeded: number; random_new: number; rename_preserved: number; move_preserved: number; pending: number; ambiguous: number; manual_repairs: number };
type IdentityCandidate = { id: number; observed_path: string; candidate_resource_ids: string[]; match_type: string; status: string; created_at: string };
const stepNames: Record<string, string> = { resource_lookup: "查询资源", resource_status: "资源状态", alist_connection: "AList 连接", authentication: "身份认证", alist_file_info: "AList 文件信息", base_path_resolve: "解析访问根目录", download_sign: "下载签名", download_entry_build: "构造 AList 下载入口", redirect_validation: "入口安全校验", redirect_ready: "302 跳转就绪" };

export default function DiagnosticsPage() {
  const queryClient = useQueryClient();
  const [id, setId] = useState("");
  const [keyword, setKeyword] = useState("");
  const [forceRefresh, setForceRefresh] = useState(true);
  const search = useQuery({ queryKey: ["diagnostic-resource-search", keyword], queryFn: () => api<SearchResponse>(`/api/search?q=${encodeURIComponent(keyword)}&object_type=resource&page_size=6`), enabled: keyword.trim().length > 0 });
  const history = useQuery({ queryKey: ["download-diagnostics"], queryFn: () => api<{ items: Diagnostic[] }>("/api/admin/downloads/diagnostics") });
  const identityStats = useQuery({ queryKey: ["identity-stats"], queryFn: () => api<IdentityStats>("/api/admin/identities/stats") });
  const identityCandidates = useQuery({ queryKey: ["identity-candidates"], queryFn: () => api<{ items: IdentityCandidate[] }>("/api/admin/identities/candidates?status=open&limit=20") });
  const diagnose = useMutation({ mutationFn: () => api<Diagnostic>("/api/admin/downloads/diagnose", { method: "POST", body: JSON.stringify({ resource_id: id.trim(), force_refresh: forceRefresh }) }), onSuccess: () => queryClient.invalidateQueries({ queryKey: ["download-diagnostics"] }) });
  const result = diagnose.data;

  return <AdminShell title="下载诊断"><div className="admin-page diagnostics-page">
    <section className="panel diagnostic-runner"><h2>测试 AList 原生下载链路</h2><p className="panel-intro">选择或输入资源 ID，服务端会检查索引、AList 文件信息、访问根目录、下载签名和安全跳转；页面只显示 AList 域名，不显示签名。</p>
      <label className="diagnostic-search"><Search /><input maxLength={SEARCH_QUERY_MAX_LENGTH} value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder="按资源名称搜索" /></label>
      {keyword && <div className="diagnostic-suggestions">{search.isFetching ? <span>正在搜索…</span> : search.data?.items.length ? search.data.items.map((item) => <button key={item.id} onClick={() => { setId(item.id); setKeyword(""); }}><strong>{item.name}</strong><small>{item.extension || item.content_type} · {item.id}</small></button>) : <span>没有匹配资源</span>}</div>}
      <div className="diagnostic-form"><input value={id} onChange={(event) => setId(event.target.value)} placeholder="Resource ID" /><label><input type="checkbox" checked={forceRefresh} onChange={(event) => setForceRefresh(event.target.checked)} />重新读取 AList 文件信息</label><button className="primary" disabled={!id.trim() || diagnose.isPending} onClick={() => diagnose.mutate()}>{diagnose.isPending ? "诊断中…" : "开始诊断"}</button></div>
      {diagnose.error && <p className="form-error">{diagnose.error.message}</p>}
    </section>

    {result && <section className="panel diagnostic-result"><header><span className={`diagnostic-status ${result.status}`}>{result.status === "success" ? <CheckCircle2 /> : <XCircle />}</span><div><h2>{result.status === "success" ? "AList 下载入口已就绪" : "下载链路异常"}</h2><p>{result.resource_name || result.resource_id}</p></div><strong>{result.duration_ms} ms</strong></header><div className="diagnostic-step-list">{result.steps?.map((step, index) => <article key={`${step.name}-${index}`}><span className={step.status}>{step.status === "failed" ? <XCircle /> : <CheckCircle2 />}</span><strong>{stepNames[step.name] || step.name}</strong><small>{step.status === "skipped" ? "未要求签名" : step.status === "failed" ? result.error_code : `${step.duration_ms} ms`}</small></article>)}</div><dl><div><dt>结果</dt><dd>{result.message}</dd></div><div><dt>AList 域名</dt><dd>{result.target_host || "未获取"}</dd></div><div><dt>访问根目录</dt><dd>{result.base_path || "未获取"}</dd></div><div><dt>下载签名</dt><dd>{result.has_sign ? "已获取" : "当前未要求"}</dd></div></dl></section>}

    <section className="panel identity-diagnostics"><h2><Fingerprint />Stable Resource ID</h2>{identityStats.isLoading ? <div className="loading">正在读取身份注册表…</div> : identityStats.error ? <p className="form-error">{identityStats.error.message}</p> : <><div className="identity-stat-grid"><article><small>身份总数</small><strong>{identityStats.data?.total ?? 0}</strong></article><article><small>Legacy 保留</small><strong>{identityStats.data?.legacy_seeded ?? 0}</strong></article><article><small>新随机 ID</small><strong>{identityStats.data?.random_new ?? 0}</strong></article><article><small>Rename / Move 保留</small><strong>{(identityStats.data?.rename_preserved ?? 0) + (identityStats.data?.move_preserved ?? 0)}</strong></article><article><small>待判定</small><strong>{identityStats.data?.pending ?? 0}</strong></article><article><small>歧义</small><strong>{identityStats.data?.ambiguous ?? 0}</strong></article></div><h3>待确认候选</h3>{identityCandidates.data?.items.length ? <div className="identity-candidate-list">{identityCandidates.data.items.map((item) => <article key={item.id}><div><strong>{item.observed_path}</strong><small>{item.match_type} · {item.candidate_resource_ids.length} 个候选 · {new Date(item.created_at).toLocaleString("zh-CN")}</small></div><b>{item.status}</b></article>)}</div> : <div className="empty compact">当前没有待确认或歧义候选。</div>}</>}</section>

    <section className="panel diagnostic-history"><h2><Clock3 />最近诊断记录</h2>{history.isLoading ? <div className="loading">正在读取…</div> : history.data?.items.length ? history.data.items.map((item) => <article key={item.id}><span className={`diagnostic-dot ${item.status}`} /><div><strong>{item.resource_id}</strong><small>{item.message}{item.target_host ? ` · ${item.target_host}` : ""}</small></div><b>{item.error_code || `${item.duration_ms} ms`}</b><time>{new Date(item.created_at).toLocaleString("zh-CN")}</time></article>) : <div className="empty compact">还没有诊断记录。</div>}</section>
  </div></AdminShell>;
}
