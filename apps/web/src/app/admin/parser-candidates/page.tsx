"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Play, Plus, RefreshCw, RotateCcw, WandSparkles } from "lucide-react";
import { useState } from "react";
import { AdminShell } from "@/components/AdminShell";
import { api } from "@/lib/api";
import {
  DEFAULT_PARSER_EVALUATION_CASES,
  parseCandidateResult,
  parserCandidateListPath,
  parserCandidateRetryPath,
  parserCandidateStatusLabel,
  type ParserCandidateStatus,
  type ParserCandidateTask,
} from "@/lib/parser-candidates";

const STATUSES: Array<ParserCandidateStatus | ""> = ["", "pending", "running", "completed", "failed", "cancelled"];
const PAGE_SIZE = 50;

export default function ParserCandidatesPage() {
  const client = useQueryClient();
  const [status, setStatus] = useState<ParserCandidateStatus | "">("");
  const [resourceFilter, setResourceFilter] = useState("");
  const [enqueueId, setEnqueueId] = useState("");
  const [maxItems, setMaxItems] = useState(20);
  const [seconds, setSeconds] = useState(10);
  const [page, setPage] = useState(1);
  const key = ["admin-parser-candidates", status, resourceFilter, page] as const;
  const candidates = useQuery({
    queryKey: key,
    queryFn: () => api<{ items: ParserCandidateTask[]; total_returned: number }>(parserCandidateListPath({ status, resourceId: resourceFilter.trim(), limit: PAGE_SIZE + 1, offset: (page - 1) * PAGE_SIZE })),
  });
  const refresh = () => client.invalidateQueries({ queryKey: ["admin-parser-candidates"] });
  const enqueue = useMutation({
    mutationFn: () => api<{ task: ParserCandidateTask; created: boolean }>("/api/admin/parser-candidates/enqueue", { method: "POST", body: JSON.stringify({ resource_id: enqueueId.trim() }) }),
    onSuccess: () => { setEnqueueId(""); refresh(); },
  });
  const batch = useMutation({
    mutationFn: () => api<{ attempted: number; stopped_reason: string }>("/api/admin/parser-candidates/batch", { method: "POST", body: JSON.stringify({ max_items: maxItems, time_budget_seconds: seconds }) }),
    onSuccess: refresh,
  });
  const recover = useMutation({
    mutationFn: () => api<{ recovered_count: number }>("/api/admin/parser-candidates/recover", { method: "POST" }),
    onSuccess: refresh,
  });
  const retry = useMutation({
    mutationFn: (taskId: string) => api<ParserCandidateTask>(parserCandidateRetryPath(taskId), { method: "POST", body: JSON.stringify({ max_retries: 3 }) }),
    onSuccess: () => {
      const visibleCount = Math.min(candidates.data?.total_returned ?? 0, PAGE_SIZE);
      const hasNext = (candidates.data?.total_returned ?? 0) > PAGE_SIZE;
      if (status === "failed" && page > 1 && visibleCount === 1 && !hasNext) setPage(page - 1);
      refresh();
    },
  });
  const evaluate = useMutation({
    mutationFn: () => api<{ samples: number; aggregate: { accuracy: number; unknown_rate: number; misclassification_rate: number } }>("/api/admin/parser-candidates/evaluate", { method: "POST", body: JSON.stringify({ cases: DEFAULT_PARSER_EVALUATION_CASES }) }),
  });

  const items = (candidates.data?.items ?? []).slice(0, PAGE_SIZE);
  const hasNextPage = (candidates.data?.total_returned ?? 0) > PAGE_SIZE;

  return <AdminShell title="解析候选">
    <div className="admin-page parser-candidate-page">
      <section className="panel parser-candidate-controls">
        <div><h2><WandSparkles />影子解析队列</h2><p className="panel-intro">解析结果只形成候选，不会覆盖人工内容或自动发布。</p></div>
        <form className="inline-form" onSubmit={(event) => { event.preventDefault(); if (enqueueId.trim()) enqueue.mutate(); }}>
          <input aria-label="资源 ID" placeholder="输入已索引资源 ID" value={enqueueId} onChange={(event) => setEnqueueId(event.target.value)} />
          <button className="primary" disabled={!enqueueId.trim() || enqueue.isPending}><Plus />加入队列</button>
        </form>
        <div className="parser-batch-controls">
          <label>最多处理<input type="number" min={1} max={500} value={maxItems} onChange={(event) => setMaxItems(Number(event.target.value))} /></label>
          <label>时间预算（秒）<input type="number" min={0} max={3600} value={seconds} onChange={(event) => setSeconds(Number(event.target.value))} /></label>
          <button type="button" className="primary" disabled={batch.isPending} onClick={() => batch.mutate()}><Play />执行一批</button>
          <button type="button" disabled={recover.isPending} onClick={() => recover.mutate()}><RotateCcw />恢复中断任务</button>
        </div>
        {(enqueue.error || batch.error || recover.error) && <p className="form-error">{(enqueue.error || batch.error || recover.error)?.message}</p>}
        {batch.data && <p className="form-success">本次尝试 {batch.data.attempted} 条，停止原因：{batch.data.stopped_reason}</p>}
        {recover.data && <p className="form-success">已恢复 {recover.data.recovered_count} 条中断任务。</p>}
        <div className="parser-evaluation">
          <button type="button" disabled={evaluate.isPending} onClick={() => evaluate.mutate()}><WandSparkles />{evaluate.isPending ? "正在评估…" : "运行固定样本评估"}</button>
          {evaluate.data && <dl><div><dt>样本</dt><dd>{evaluate.data.samples}</dd></div><div><dt>准确率</dt><dd>{(evaluate.data.aggregate.accuracy * 100).toFixed(1)}%</dd></div><div><dt>未知率</dt><dd>{(evaluate.data.aggregate.unknown_rate * 100).toFixed(1)}%</dd></div><div><dt>误判率</dt><dd>{(evaluate.data.aggregate.misclassification_rate * 100).toFixed(1)}%</dd></div></dl>}
          {evaluate.error && <p className="form-error">{evaluate.error.message}</p>}
        </div>
      </section>

      <section className="panel parser-candidate-list">
        <div className="panel-toolbar"><div><h2>候选任务</h2><p>本页 {items.length} 条</p></div><div className="parser-filters">
          <select aria-label="状态筛选" value={status} onChange={(event) => { setStatus(event.target.value as ParserCandidateStatus | ""); setPage(1); }}>
            {STATUSES.map((value) => <option value={value} key={value || "all"}>{value ? parserCandidateStatusLabel(value) : "全部状态"}</option>)}
          </select>
          <input aria-label="资源筛选" placeholder="按资源 ID 筛选" value={resourceFilter} onChange={(event) => { setResourceFilter(event.target.value); setPage(1); }} />
          <button type="button" aria-label="刷新" onClick={() => candidates.refetch()}><RefreshCw /></button>
        </div></div>
        {candidates.isLoading ? <div className="loading">正在读取…</div>
          : candidates.error ? <div className="empty error-state">{candidates.error.message}</div>
          : items.length ? <div>{items.map((task) => <CandidateRow task={task} onRetry={() => retry.mutate(task.task_id)} retrying={retry.isPending} key={task.task_id} />)}</div>
          : <div className="empty">当前没有候选任务。</div>}
        {(page > 1 || hasNextPage) && <nav className="pagination" aria-label="解析候选分页"><button type="button" disabled={page <= 1 || candidates.isFetching} onClick={() => setPage((value) => Math.max(1, value - 1))}>上一页</button><span>第 {page} 页</span><button type="button" disabled={!hasNextPage || candidates.isFetching} onClick={() => setPage((value) => value + 1)}>下一页</button></nav>}
      </section>
    </div>
  </AdminShell>;
}

function CandidateRow({ task, onRetry, retrying }: { task: ParserCandidateTask; onRetry: () => void; retrying: boolean }) {
  const result = parseCandidateResult(task.result_json);
  return <article className="parser-candidate-row">
    <header><div><strong>{task.resource_id}</strong><small>{task.task_id} · 规则 {task.parser_version}</small></div><span className={`parser-status ${task.status}`}>{parserCandidateStatusLabel(task.status)}</span></header>
    {task.error_text && <p className="form-error">{task.error_text}</p>}
    {result && <details><summary>查看解析依据</summary><pre>{JSON.stringify(result, null, 2)}</pre></details>}
    <footer><time>{new Date(task.updated_at).toLocaleString("zh-CN")}</time>{task.status === "failed" && <button type="button" disabled={retrying} onClick={onRetry}><RotateCcw />重试（{task.retry_count}/3）</button>}</footer>
  </article>;
}
