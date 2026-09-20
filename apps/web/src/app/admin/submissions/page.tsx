"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ClipboardList, ExternalLink, Search, Trash2 } from "lucide-react";
import { useState } from "react";
import { AdminShell } from "@/components/AdminShell";
import { api, type SearchResponse } from "@/lib/api";
import { SEARCH_QUERY_MAX_LENGTH } from "@/lib/search-query";
import { buildReviewPayload, defaultReviewAction, isPublishReady, type ReviewAction } from "@/lib/submission-review";

type Submission = {
  id: number;
  user_id: number;
  username: string;
  resource_name: string;
  resource_type: string;
  description: string;
  source_url: string;
  download_url: string;
  copyright_note: string;
  note: string;
  status: "pending" | "approved" | "rejected" | "published";
  admin_note: string;
  reviewed_by: string;
  reviewed_at: string | null;
  created_at: string;
  updated_at: string;
  published_resource_id: string | null;
};

const statusLabel: Record<Submission["status"], string> = { pending: "待审核", approved: "已通过", rejected: "已拒绝", published: "已发布" };
const typeLabel: Record<string, string> = { software: "软件", image: "图库", video: "视频", document: "教程", file: "文件" };

function formatTime(value: string | null) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false });
}

export default function AdminSubmissionsPage() {
  const client = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<"all" | Submission["status"]>("pending");
  const [search, setSearch] = useState("");
  const [reviewingId, setReviewingId] = useState<number | null>(null);
  const [action, setAction] = useState<ReviewAction>("approve");
  const [adminNote, setAdminNote] = useState("");
  const [resourceId, setResourceId] = useState("");
  const [resourceKeyword, setResourceKeyword] = useState("");
  const [selectedResourceName, setSelectedResourceName] = useState("");
  const [deletingId, setDeletingId] = useState<number | null>(null);

  const query = useQuery({ queryKey: ["admin-submissions", statusFilter], queryFn: () => api<{ items: Submission[] }>(`/api/admin/submissions${statusFilter !== "all" ? `?status=${statusFilter}` : ""}`) });
  const resourceSearch = useQuery({
    queryKey: ["submission-publish-resource-search", resourceKeyword],
    queryFn: () => api<SearchResponse>(`/api/search?q=${encodeURIComponent(resourceKeyword.trim())}&object_type=resource&page_size=6`),
    enabled: action === "publish" && resourceKeyword.trim().length > 0,
  });
  const review = useMutation({
    mutationFn: () => api<Submission>(`/api/admin/submissions/${reviewingId}`, { method: "PATCH", body: JSON.stringify(buildReviewPayload(action, adminNote, resourceId)) }),
    onSuccess: () => { setReviewingId(null); setAdminNote(""); setResourceId(""); setResourceKeyword(""); setSelectedResourceName(""); client.invalidateQueries({ queryKey: ["admin-submissions"] }); },
  });
  const remove = useMutation({
    mutationFn: (id: number) => api<{ ok: boolean }>(`/api/admin/submissions/${id}`, { method: "DELETE" }),
    onSuccess: () => { setDeletingId(null); client.invalidateQueries({ queryKey: ["admin-submissions"] }); },
  });

  const items = (query.data?.items ?? []).filter((item) => {
    if (!search.trim()) return true;
    const needle = search.trim().toLowerCase();
    return `${item.resource_name} ${item.username} ${item.description} ${item.download_url}`.toLowerCase().includes(needle);
  });

  const reviewingItem = reviewingId !== null ? (query.data?.items ?? []).find((item) => item.id === reviewingId) : undefined;
  const reviewable = reviewingItem ? defaultReviewAction(reviewingItem.status) !== null : false;
  const publishReady = isPublishReady(action, resourceId);

  function openReview(id: number, defaultAction: ReviewAction) {
    review.reset();
    setReviewingId(id);
    setAction(defaultAction);
    setAdminNote("");
    setResourceId("");
    setResourceKeyword("");
    setSelectedResourceName("");
  }

  function closeReview() {
    review.reset();
    setReviewingId(null);
    setAdminNote("");
    setResourceId("");
    setResourceKeyword("");
    setSelectedResourceName("");
  }

  return <AdminShell title="投稿审核"><div className="admin-page">
    <section className="panel">
      <div className="panel-toolbar"><div><h2><ClipboardList />投稿审核</h2><p>共 {items.length} 条{statusFilter !== "all" ? `（${statusLabel[statusFilter]}）` : ""}</p></div><div className="share-toolbar submission-filter-toolbar"><div className="small-search"><Search /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索资源名 / 提交者 / 链接" /></div><select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as "all" | Submission["status"])}><option value="all">全部</option>{Object.entries(statusLabel).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></div></div>
      <div className="table-scroll submission-table-scroll" role="region" aria-label="投稿表格" tabIndex={0}><div className="table-head submission-table-head"><span>资源</span><span>提交者</span><span>状态</span><span>提交时间</span><span>操作</span></div>
      {query.isLoading ? <div className="loading">正在读取投稿…</div> : query.error ? <div className="empty error-state">加载投稿失败：{query.error.message}<button type="button" onClick={() => query.refetch()}>重试</button></div> : items.length ? items.map((item) => <div className="table-row submission-table-row" key={item.id}>
        <span><b>{item.resource_name}<small>{typeLabel[item.resource_type] ?? item.resource_type}{item.download_url ? " · 含网盘链接" : ""}</small></b></span>
        <span><b>{item.username}</b><small>#{item.user_id}</small></span>
        <span><b className={`submission-status ${item.status}`}>{statusLabel[item.status]}</b>{item.reviewed_at && <small>{formatTime(item.reviewed_at)}</small>}</span>
        <span>{formatTime(item.created_at)}</span>
        <span className="submission-actions">
          {item.download_url && <a title="打开网盘链接" href={item.download_url} target="_blank" rel="noreferrer"><ExternalLink /></a>}
          {item.status === "pending" && <button onClick={() => openReview(item.id, "approve")}>审核</button>}
          {item.status === "approved" && <button onClick={() => openReview(item.id, "publish")}>发布</button>}
          {item.status === "published" && item.published_resource_id && <a href={`/resource/${encodeURIComponent(item.published_resource_id)}`} title="查看发布资源">查看资源</a>}
          {item.status === "rejected" && (deletingId === item.id ? <span className="submission-delete-confirm">
            <button className="danger" disabled={remove.isPending} onClick={() => remove.mutate(item.id)}>{remove.isPending ? "删除中…" : "确认删除"}</button>
            <button onClick={() => setDeletingId(null)}>取消</button>
          </span> : <button className="danger-icon" title="删除投稿" onClick={() => setDeletingId(item.id)}><Trash2 size={16} /></button>)}
        </span>
      </div>) : <div className="empty">没有匹配的投稿。</div>}</div>
      {(review.error || remove.error) && <p className="form-error">{(review.error || remove.error)?.message}</p>}
    </section>

    {reviewingId !== null && reviewable && (query.data?.items ?? []).find((item) => item.id === reviewingId) && <div className="submission-detail-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) closeReview(); }}>
      {(() => { const item = (query.data?.items ?? []).find((it) => it.id === reviewingId)!; return <section className="panel submission-detail" role="dialog" aria-modal="true" aria-label="投稿详情" onMouseDown={(event) => event.stopPropagation()}>
        <h2>{item.resource_name}</h2>
        <dl>
          <div><dt>资源类型</dt><dd>{typeLabel[item.resource_type] ?? item.resource_type}</dd></div>
          <div><dt>提交者</dt><dd>{item.username} (#{item.user_id})</dd></div>
          <div><dt>状态</dt><dd>{statusLabel[item.status]}</dd></div>
          <div><dt>提交时间</dt><dd>{formatTime(item.created_at)}</dd></div>
          <div><dt>资源简介</dt><dd>{item.description || "—"}</dd></div>
          <div><dt>来源网址</dt><dd>{item.source_url ? <a href={item.source_url} target="_blank" rel="noreferrer">{item.source_url}</a> : "—"}</dd></div>
          <div><dt>网盘链接</dt><dd>{item.download_url ? <a href={item.download_url} target="_blank" rel="noreferrer">{item.download_url}</a> : "—"}</dd></div>
          <div><dt>版权说明</dt><dd>{item.copyright_note || "—"}</dd></div>
          <div><dt>备注</dt><dd>{item.note || "—"}</dd></div>
          {item.admin_note && <div><dt>审核备注</dt><dd>{item.admin_note}</dd></div>}
        </dl>
        <div className="submission-review-inline">
          {item.status === "pending"
            ? <select value={action} onChange={(event) => setAction(event.target.value as ReviewAction)}><option value="approve">通过</option><option value="reject">拒绝</option></select>
            : <strong>发布已审核投稿</strong>}
          <input value={adminNote} onChange={(event) => setAdminNote(event.target.value)} placeholder="审核备注（可选）" maxLength={500} />
          {action === "publish" && <>
            <label className="diagnostic-search"><Search /><input maxLength={SEARCH_QUERY_MAX_LENGTH} value={resourceKeyword} onChange={(event) => setResourceKeyword(event.target.value)} placeholder="按资源名称搜索已索引资源" /></label>
            {resourceKeyword && <div className="diagnostic-suggestions">
              {resourceSearch.isFetching ? <span>正在搜索…</span>
                : resourceSearch.error ? <><span>搜索失败：{resourceSearch.error.message}</span><button type="button" onClick={() => resourceSearch.refetch()}>重试</button></>
                : resourceSearch.data?.items.length ? resourceSearch.data.items.map((resource) => <button key={resource.id} type="button" onClick={() => { setResourceId(resource.id); setSelectedResourceName(resource.name); setResourceKeyword(""); }}><strong>{resource.name}</strong><small>{typeLabel[resource.content_type] ?? resource.content_type} · {resource.extension || "资源"} · {resource.id}</small></button>)
                : <span>没有匹配资源</span>}
            </div>}
            <input value={resourceId} onChange={(event) => { setResourceId(event.target.value); setSelectedResourceName(""); }} placeholder="已选资源 ID，也可手动输入" maxLength={200} />
            {resourceId && <small>将绑定资源：{selectedResourceName ? `${selectedResourceName} · ` : ""}{resourceId}</small>}
          </>}
          <button className="primary" disabled={review.isPending || !publishReady} onClick={() => review.mutate()}>{review.isPending ? "处理中…" : item.status === "approved" ? "确认发布" : "提交审核"}</button>
          <button onClick={closeReview}>关闭</button>
        </div>
      </section>; })()}
    </div>}
  </div></AdminShell>;
}
