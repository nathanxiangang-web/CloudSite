"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Loader2, RefreshCw, Wand2, XCircle } from "lucide-react";
import { useState } from "react";
import { AdminShell } from "@/components/AdminShell";
import { api } from "@/lib/api";

type SuggestionKind = "new_entry" | "new_release" | "asset" | "candidate_duplicate" | "conflict";
type SuggestionStatus = "pending" | "reviewed" | "applied" | "rejected";

type Suggestion = {
  suggestion_id: string;
  source_file_id: string;
  file_fingerprint: string;
  parser_version: string;
  suggestion_kind: SuggestionKind;
  target_entry_id: string | null;
  target_release_id: string | null;
  target_asset_id: string | null;
  suggested_fields: Record<string, unknown> | null;
  evidence: Record<string, unknown> | null;
  confidence: number;
  status: SuggestionStatus;
  reviewed_by: string;
  reviewed_at: string | null;
  applied_at: string | null;
  applied_revision_id: string | null;
  reject_reason: string;
  created_at: string;
  updated_at: string;
};

type SuggestionList = { items: Suggestion[]; page: number; page_size: number; total: number; total_pages: number };
type BatchResult = { results: { suggestion_id: string; success: boolean; error: string; entry_id: string | null; release_id: string | null; asset_id: string | null }[]; succeeded: number; failed: number };
type GenerateResult = { created: number; skipped: number };

const kindLabel: Record<SuggestionKind, string> = {
  new_entry: "新建条目",
  new_release: "新建版本",
  asset: "补充资产",
  candidate_duplicate: "候选重复",
  conflict: "冲突",
};

const statusLabel: Record<SuggestionStatus, string> = {
  pending: "待审核",
  reviewed: "已审核",
  applied: "已应用",
  rejected: "已拒绝",
};

const kindTabs: { kind: SuggestionKind | "all"; label: string }[] = [
  { kind: "all", label: "全部" },
  { kind: "new_entry", label: "新建条目" },
  { kind: "new_release", label: "新建版本" },
  { kind: "asset", label: "补充资产" },
  { kind: "candidate_duplicate", label: "候选重复" },
  { kind: "conflict", label: "冲突" },
];

function formatTime(value: string | null) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false });
}

function confidenceLabel(value: number) {
  if (value >= 0.7) return "高";
  if (value >= 0.5) return "中";
  return "低";
}

function shortId(value: string | null) {
  if (!value) return "—";
  return value.length > 16 ? `${value.slice(0, 8)}…${value.slice(-6)}` : value;
}

export default function AdminAutomationPage() {
  const client = useQueryClient();
  const [kindFilter, setKindFilter] = useState<SuggestionKind | "all">("all");
  const [statusFilter, setStatusFilter] = useState<SuggestionStatus | "all">("pending");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [batchResult, setBatchResult] = useState<BatchResult | null>(null);
  const [page, setPage] = useState(1);

  const queryKey = ["admin-automation-suggestions", kindFilter, statusFilter, page];
  const query = useQuery({
    queryKey,
    queryFn: () => {
      const params = new URLSearchParams({ page: String(page), page_size: "50" });
      if (kindFilter !== "all") params.set("suggestion_kind", kindFilter);
      if (statusFilter !== "all") params.set("status", statusFilter);
      return api<SuggestionList>(`/api/admin/automation/suggestions?${params.toString()}`);
    },
  });

  const generate = useMutation({
    mutationFn: () => api<GenerateResult>("/api/admin/automation/generate", { method: "POST", body: JSON.stringify({ limit: 500 }) }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["admin-automation-suggestions"] }),
  });

  const batchApply = useMutation({
    mutationFn: (ids: string[]) => api<BatchResult>("/api/admin/automation/suggestions/batch-apply", { method: "POST", body: JSON.stringify({ suggestion_ids: ids }) }),
    onSuccess: (data) => { setBatchResult(data); setSelected(new Set()); client.invalidateQueries({ queryKey: ["admin-automation-suggestions"] }); },
  });

  const batchReject = useMutation({
    mutationFn: (ids: string[]) => api<BatchResult>("/api/admin/automation/suggestions/batch-reject", { method: "POST", body: JSON.stringify({ suggestion_ids: ids }) }),
    onSuccess: (data) => { setBatchResult(data); setSelected(new Set()); client.invalidateQueries({ queryKey: ["admin-automation-suggestions"] }); },
  });

  const applyOne = useMutation({
    mutationFn: (id: string) => api<{ suggestion_id: string; success: boolean }>(`/api/admin/automation/suggestions/${id}/apply`, { method: "POST" }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["admin-automation-suggestions"] }),
  });

  const rejectOne = useMutation({
    mutationFn: (id: string) => api<Suggestion>(`/api/admin/automation/suggestions/${id}/reject`, { method: "POST", body: JSON.stringify({ reason: "" }) }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["admin-automation-suggestions"] }),
  });

  const revertOne = useMutation({
    mutationFn: (id: string) => api<Suggestion>(`/api/admin/automation/suggestions/${id}/revert`, { method: "POST" }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["admin-automation-suggestions"] }),
  });

  const items = query.data?.items ?? [];

  function toggleSelect(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleSelectAll() {
    if (selected.size === items.length && items.length > 0) {
      setSelected(new Set());
    } else {
      setSelected(new Set(items.map((item) => item.suggestion_id)));
    }
  }

  const selectedIds = Array.from(selected);

  return (
    <AdminShell title="整理工作台">
      <div className="admin-page">
        <section className="panel">
          <div className="panel-toolbar">
            <div>
              <h2><Wand2 />整理工作台</h2>
              <p>共 {query.data?.total ?? 0} 条建议{kindFilter !== "all" ? `（${kindLabel[kindFilter]}）` : ""}</p>
            </div>
            <div className="share-toolbar">
              <button className="primary" disabled={generate.isPending} onClick={() => generate.mutate()}>
                {generate.isPending ? <Loader2 className="spin" /> : <RefreshCw size={16} />}
                {generate.isPending ? "生成中…" : "生成建议"}
              </button>
              {generate.data && <span className="form-hint">新建 {generate.data.created}，跳过 {generate.data.skipped}</span>}
            </div>
          </div>

          <div className="automation-tabs">
            {kindTabs.map((tab) => (
              <button key={tab.kind} className={kindFilter === tab.kind ? "active" : ""} onClick={() => { setKindFilter(tab.kind); setPage(1); }}>
                {tab.label}
              </button>
            ))}
            <select value={statusFilter} onChange={(event) => { setStatusFilter(event.target.value as SuggestionStatus | "all"); setPage(1); }} style={{ marginLeft: "auto" }}>
              <option value="all">全部状态</option>
              <option value="pending">待审核</option>
              <option value="reviewed">已审核</option>
              <option value="applied">已应用</option>
              <option value="rejected">已拒绝</option>
            </select>
          </div>

          {selected.size > 0 && (
            <div className="automation-batch-bar">
              <span>已选 {selected.size} 条</span>
              <button className="primary" disabled={batchApply.isPending} onClick={() => batchApply.mutate(selectedIds)}>
                {batchApply.isPending ? "执行中…" : "批量应用"}
              </button>
              <button disabled={batchReject.isPending} onClick={() => batchReject.mutate(selectedIds)}>
                {batchReject.isPending ? "执行中…" : "批量拒绝"}
              </button>
              <button onClick={() => setSelected(new Set())}>取消选择</button>
            </div>
          )}

          <div className="table-scroll" role="region" aria-label="建议表格" tabIndex={0}>
            <div className="table-head automation-table-head">
              <span><input type="checkbox" checked={selected.size === items.length && items.length > 0} onChange={toggleSelectAll} aria-label="全选" /></span>
              <span>来源文件</span>
              <span>类型</span>
              <span>拟关联</span>
              <span>置信</span>
              <span>状态</span>
              <span>操作</span>
            </div>
            {query.isLoading ? (
              <div className="loading">正在读取建议…</div>
            ) : items.length ? (
              items.map((item) => (
                <div className="table-row automation-table-row" key={item.suggestion_id}>
                  <span><input type="checkbox" checked={selected.has(item.suggestion_id)} onChange={() => toggleSelect(item.suggestion_id)} aria-label={`选择 ${item.suggestion_id}`} /></span>
                  <span><b>{shortId(item.source_file_id)}</b><small>{formatTime(item.created_at)}</small></span>
                  <span><b className={`suggestion-kind ${item.suggestion_kind}`}>{kindLabel[item.suggestion_kind]}</b></span>
                  <span>
                    {item.target_entry_id && <small>条目 {shortId(item.target_entry_id)}</small>}
                    {item.target_release_id && <small>版本 {shortId(item.target_release_id)}</small>}
                    {item.target_asset_id && <small>资产 {shortId(item.target_asset_id)}</small>}
                    {!item.target_entry_id && !item.target_release_id && !item.target_asset_id && <small>—</small>}
                  </span>
                  <span><b className={`confidence-${confidenceLabel(item.confidence)}`}>{confidenceLabel(item.confidence)}</b><small>{Math.round(item.confidence * 100)}%</small></span>
                  <span><b className={`suggestion-status ${item.status}`}>{statusLabel[item.status]}</b></span>
                  <span className="automation-actions">
                    {item.status === "pending" && <>
                      <button className="primary" disabled={applyOne.isPending} onClick={() => applyOne.mutate(item.suggestion_id)}>应用</button>
                      <button disabled={rejectOne.isPending} onClick={() => rejectOne.mutate(item.suggestion_id)}>拒绝</button>
                    </>}
                    {item.status === "applied" && <button disabled={revertOne.isPending} onClick={() => revertOne.mutate(item.suggestion_id)}>撤销</button>}
                    {item.status === "rejected" && <small>{item.reject_reason || "已拒绝"}</small>}
                  </span>
                </div>
              ))
            ) : (
              <div className="empty">没有匹配的建议。点击「生成建议」扫描资源。</div>
            )}
          </div>

          {query.data && query.data.total_pages > 1 && (
            <div className="pagination">
              <button disabled={page <= 1} onClick={() => setPage(page - 1)}>上一页</button>
              <span>第 {page} / {query.data.total_pages} 页</span>
              <button disabled={page >= query.data.total_pages} onClick={() => setPage(page + 1)}>下一页</button>
            </div>
          )}
        </section>

        {batchResult && (
          <section className="panel">
            <div className="panel-toolbar">
              <div><h2>批量操作结果</h2><p>成功 {batchResult.succeeded}，失败 {batchResult.failed}</p></div>
              <button onClick={() => setBatchResult(null)}>关闭</button>
            </div>
            <div className="table-scroll">
              {batchResult.results.map((r) => (
                <div className="table-row automation-batch-result-row" key={r.suggestion_id}>
                  <span>{r.success ? <CheckCircle2 className="success-icon" /> : <XCircle className="error-icon" />}</span>
                  <span>{shortId(r.suggestion_id)}</span>
                  <span>{r.success ? "成功" : "失败"}</span>
                  {!r.success && r.error && <span className="form-error">{r.error}</span>}
                  {r.success && r.entry_id && <span>→ {shortId(r.entry_id)}</span>}
                </div>
              ))}
            </div>
          </section>
        )}

        {items.length > 0 && (
          <section className="panel">
            <h2>建议详情预览</h2>
            <p className="form-hint">展开查看选中建议的建议字段、依据与预期影响。</p>
            <div className="automation-detail-list">
              {items.slice(0, 10).map((item) => (
                <details key={item.suggestion_id}>
                  <summary>{kindLabel[item.suggestion_kind]} · {shortId(item.source_file_id)} · {statusLabel[item.status]}</summary>
                  <dl>
                    <div><dt>建议 ID</dt><dd>{item.suggestion_id}</dd></div>
                    <div><dt>来源文件</dt><dd>{item.source_file_id}</dd></div>
                    <div><dt>文件指纹</dt><dd>{shortId(item.file_fingerprint)}</dd></div>
                    <div><dt>解析器版本</dt><dd>{item.parser_version}</dd></div>
                    <div><dt>建议字段</dt><dd><pre>{JSON.stringify(item.suggested_fields, null, 2)}</pre></dd></div>
                    <div><dt>依据</dt><dd><pre>{JSON.stringify(item.evidence, null, 2)}</pre></dd></div>
                    <div><dt>置信度</dt><dd>{Math.round(item.confidence * 100)}%（{confidenceLabel(item.confidence)}）</dd></div>
                  </dl>
                </details>
              ))}
            </div>
          </section>
        )}

        {(applyOne.error || rejectOne.error || revertOne.error || generate.error) && (
          <p className="form-error">{(applyOne.error || rejectOne.error || revertOne.error || generate.error)?.message}</p>
        )}
      </div>
    </AdminShell>
  );
}
