"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CloudDownload, LogIn, RefreshCw, Send } from "lucide-react";
import Link from "next/link";
import { FormEvent, useState } from "react";
import { PublicShell } from "@/components/PublicShell";
import { SiteFooter } from "@/components/SiteFooter";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type CloudDownloadTask = {
  id: number;
  name: string;
  status: string;
  percent: number;
  created_at: string;
};

const REFRESH_INTERVAL = 30000;

const statusLabel: Record<string, string> = {
  pending: "\u5f85\u5904\u7406",
  running: "\u4e0b\u8f7d\u4e2d",
  completed: "\u5df2\u5b8c\u6210",
  failed: "\u5931\u8d25",
};

function formatTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false });
}

function isSupportedUrl(value: string) {
  const candidate = value.trim();
  return candidate.length <= 2048 && !/\s/.test(candidate) && (
    /^https?:\/\/[^/]+/i.test(candidate) ||
    /^magnet:\?\S+/i.test(candidate) ||
    /^ed2k:\/\/\|[^|]+\|/i.test(candidate)
  );
}

export default function CloudDownloadPage() {
  const auth = useAuth();
  const queryClient = useQueryClient();
  const [url, setUrl] = useState("");
  const authenticated = Boolean(auth.data?.authenticated);
  const userId = auth.data?.user?.id ?? null;
  const tasksQueryKey = ["cloud-download-tasks", userId] as const;

  const tasks = useQuery({
    queryKey: tasksQueryKey,
    queryFn: () => api<{ items: CloudDownloadTask[] }>("/api/cloud-download/tasks"),
    enabled: authenticated && userId !== null,
    refetchInterval: authenticated ? REFRESH_INTERVAL : false,
  });

  const submit = useMutation({
    mutationFn: () => api<CloudDownloadTask>("/api/cloud-download/tasks", {
      method: "POST",
      body: JSON.stringify({ url: url.trim() }),
    }),
    onSuccess: () => {
      setUrl("");
      queryClient.invalidateQueries({ queryKey: tasksQueryKey });
    },
  });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!authenticated || !url.trim() || !isSupportedUrl(url)) return;
    submit.mutate();
  };

  const items = tasks.data?.items ?? [];
  const invalidUrl = url.trim().length > 0 && !isSupportedUrl(url);

  return <PublicShell><div className="page cloud-download-page">
    <header className="submit-hero"><span><CloudDownload /></span><div><h1>{"\u4e91\u4e0b\u8f7d"}</h1><p>{"\u8f93\u5165\u8d44\u6e90\u94fe\u63a5\uff0c\u7cfb\u7edf\u4f1a\u5728\u540e\u53f0\u62c9\u53d6\u5e76\u7f13\u5b58\u5230\u4e91\u7aef\u3002\u53ef\u67e5\u770b\u5f53\u524d\u8d26\u53f7\u7684\u4e0b\u8f7d\u4efb\u52a1\u53ca\u5176\u8fdb\u5ea6\u3002"}</p></div></header>

    {!authenticated ? <section className="panel cloud-download-auth"><h2><LogIn />{"\u9700\u8981\u767b\u5f55"}</h2><p>{"\u4e91\u4e0b\u8f7d\u9700\u8981\u767b\u5f55 CloudSite \u8d26\u53f7\u540e\u4f7f\u7528\u3002"}</p><Link className="button primary" href="/login">{"\u524d\u5f80\u767b\u5f55"}</Link></section> : <>
      <div className="submit-layout">
        <form className="submit-form cloud-download-form" onSubmit={onSubmit}>
          <label className="wide">{"\u8d44\u6e90\u94fe\u63a5 *"}<input required maxLength={2048} value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://... / magnet:? / ed2k://" /></label>
          {invalidUrl && <p className="form-error wide">{"\u652f\u6301 HTTP、HTTPS、magnet \u548c ed2k \u94fe\u63a5"}</p>}
          <div className="submit-actions wide"><button className="primary" disabled={!url.trim() || invalidUrl || submit.isPending} type="submit"><Send />{submit.isPending ? "\u6b63\u5728\u63d0\u4ea4\u2026" : "\u63d0\u4ea4\u4e0b\u8f7d"}</button></div>
          {submit.isSuccess && <p className="submit-message wide">{"\u4e0b\u8f7d\u4efb\u52a1\u5df2\u521b\u5efa\uff0c\u53ef\u5728\u4e0b\u65b9\u67e5\u770b\u8fdb\u5ea6\u3002"}</p>}
          {submit.error && <p className="form-error wide">{submit.error.message}</p>}
        </form>
        <aside className="submit-aside">
          <h2>{"\u4e91\u4e0b\u8f7d"}</h2>
          <p>{"\u63d0\u4ea4\u94fe\u63a5\u540e\u7cfb\u7edf\u81ea\u52a8\u62c9\u53d6\u8d44\u6e90\u5e76\u7f13\u5b58\u5230\u4e91\u7aef\uff0c\u65e0\u9700\u8f93\u5165\u7f51\u76d8\u8d26\u53f7\u5bc6\u7801\u3002"}</p>
          <h3>{"\u4efb\u52a1\u72b6\u6001"}</h3>
          <p>{"\u9875\u9762\u4f1a\u5b9a\u671f\u5237\u65b0\u4efb\u52a1\u5217\u8868\uff0c\u5c55\u793a\u6bcf\u4e2a\u4efb\u52a1\u7684\u72b6\u6001\u548c\u4e0b\u8f7d\u767e\u5206\u6bd4\u3002"}</p>
        </aside>
      </div>

      <section className="panel cloud-download-tasks-panel">
        <h2><RefreshCw />{"\u6211\u7684\u4e0b\u8f7d\u4efb\u52a1"}</h2>
        {tasks.isLoading ? <div className="loading">{"\u6b63\u5728\u52a0\u8f7d\u4efb\u52a1\u2026"}</div>
          : tasks.error ? <div className="empty error-state">{"\u52a0\u8f7d\u5931\u8d25\uff1a"}{tasks.error.message}</div>
          : items.length === 0 ? <div className="empty">{"\u8fd8\u6ca1\u6709\u4e0b\u8f7d\u4efb\u52a1\u3002\u8f93\u5165\u94fe\u63a5\u63d0\u4ea4\u7b2c\u4e00\u4e2a\u4efb\u52a1\u5427\u3002"}</div>
          : <div className="cloud-download-task-list">{items.map((task) => <article className="cloud-download-task-item" key={task.id}>
            <div className="cloud-download-task-copy"><strong>{task.name}</strong><small>{formatTime(task.created_at)}</small></div>
            <div className="cloud-download-task-progress"><div className="cloud-download-progress-bar"><span style={{ width: `${Math.max(0, Math.min(100, task.percent))}%` }} /></div><b>{Math.max(0, Math.min(100, task.percent))}%</b></div>
            <b className={`cloud-download-status ${task.status}`}>{statusLabel[task.status] ?? task.status}</b>
          </article>)}</div>}
      </section>
    </>}
    <SiteFooter />
  </div></PublicShell>;
}
