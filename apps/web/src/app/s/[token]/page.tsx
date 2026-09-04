"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { Clock3, Download, KeyRound, Link2, Loader2 } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import type { CSSProperties, ReactNode } from "react";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { Brand } from "@/components/Brand";
import { ResourceIcon } from "@/components/ResourceIcon";
import { api, Collection, Folder, formatBytes, Resource, Share } from "@/lib/api";

type SharePageSettings = { site_name: string; share_image_url: string };
type ShareMeta = {
  token: string;
  status: "code_required" | "direct" | "cancelled" | "expired" | "invalid_target" | "migration_pending";
  title: string;
  access_mode: "code" | "direct";
  expires_at: string | null;
  cancel_reason?: string | null;
};
type FolderShare = { folder: Folder; folders: Folder[]; resources: Resource[] };
type SharePayload = { share: Share; target: Resource | Collection | FolderShare };

const statusCopy: Record<string, [string, string]> = {
  cancelled: ["分享已取消", "管理员已关闭这个分享。"],
  expired: ["分享已过期", "这个分享的有效期已经结束。"],
  invalid_target: ["目标不可用", "分享对应的资源暂时不可用。"],
  migration_pending: ["分享待升级", "这个旧版分享需要管理员升级后才能匿名访问。"],
};

export default function SharePage() {
  const { token } = useParams<{ token: string }>();
  const [code, setCode] = useState("");
  const [captchaRequired, setCaptchaRequired] = useState(false);
  const appearance = useQuery({ queryKey: ["share-page-settings"], queryFn: () => api<SharePageSettings>("/api/public/share-page"), retry: false });
  const frame = { siteName: appearance.data?.site_name || "CloudSite", imageUrl: appearance.data?.share_image_url || "" };

  const meta = useQuery({ queryKey: ["share-meta", token], queryFn: () => api<ShareMeta>(`/api/public/shares/${token}`), retry: false });
  const content = useQuery({ queryKey: ["share-content", token], queryFn: () => api<SharePayload>(`/s/${token}/content`), enabled: false, retry: false });
  const verify = useMutation({
    mutationFn: () => api<{ ok: boolean }>(`/s/${token}/verify`, {
      method: "POST",
      body: JSON.stringify({ code, captcha_token: captchaRequired ? "manual-challenge-completed" : null }),
    }),
    onSuccess: () => content.refetch(),
    onError: (error: Error & { code?: string }) => {
      if (error.code === "SHARE_CAPTCHA_REQUIRED" || error.message.includes("captcha_required")) setCaptchaRequired(true);
    },
  });

  useEffect(() => {
    if (meta.data?.status === "direct") window.location.replace(`/s/${token}/d`);
  }, [meta.data?.status, token]);

  const resources = useMemo(() => {
    if (!content.data) return [];
    const { share, target } = content.data;
    if (share.object_type === "resource") return [target as Resource];
    if (share.object_type === "collection") return (target as Collection).items ?? [];
    return (target as FolderShare).resources;
  }, [content.data]);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (code.trim().length === 4) verify.mutate();
  }

  if (meta.isLoading) return <ShareFrame {...frame}><div className="share-loading">正在打开分享...</div></ShareFrame>;
  if (!meta.data) return <ShareState {...frame} title="分享不存在" message={meta.error?.message || "请确认链接是否完整。"} />;
  if (meta.data.status === "direct") return <ShareFrame {...frame}><div className="share-loading"><Loader2 />正在准备下载...</div></ShareFrame>;
  if (meta.data.status !== "code_required") {
    const [title, message] = statusCopy[meta.data.status] ?? ["分享不可用", "这个分享暂时无法访问。"];
    return <ShareState {...frame} title={title} message={message} />;
  }

  return <ShareFrame {...frame}><main className="share-verify-card">
    <header className="share-verify-hero">
      <span><Link2 /></span>
      <div>
        <p>资源分享</p>
        <h1>{meta.data.title || "好资源，与你分享"}</h1>
        <small><Clock3 />{meta.data.expires_at ? `有效至 ${new Date(meta.data.expires_at).toLocaleString("zh-CN")}` : "长期有效"}</small>
      </div>
    </header>
    {!content.data ? <section className="share-code-panel">
      <form onSubmit={submit}>
        <label htmlFor="share-code-input">请输入提取码</label>
        <input
          id="share-code-input"
          className="share-code-input"
          value={code}
          onChange={(event) => setCode(event.target.value.toUpperCase().slice(0, 4))}
          inputMode="text"
          maxLength={4}
          autoComplete="one-time-code"
          autoCapitalize="characters"
          spellCheck={false}
          placeholder="请输入提取码，不区分大小写"
          autoFocus
        />
        <button className="primary" disabled={verify.isPending || code.trim().length !== 4}>{verify.isPending ? "正在验证..." : "提取文件"}</button>
      </form>
      {captchaRequired && <p className="share-note">请完成验证码挑战后重试。</p>}
      {verify.error && <p className="form-error">{verify.error.message}</p>}
      <p className="share-code-help">提取码由分享者提供</p>
    </section> : <section className="share-resource-grid">{resources.length ? resources.map((item) => <ShareResourceCard key={item.id} item={item} token={token} single={content.data.share.object_type === "resource"} />) : <div className="empty">分享内容为空。</div>}</section>}
  </main></ShareFrame>;
}

function ShareResourceCard({ item, token, single }: { item: Resource; token: string; single: boolean }) {
  const href = single ? `/s/${token}/d` : `/s/${token}/d/${item.id}`;
  return <article className="resource-card">
    <span className="resource-icon-link"><ResourceIcon item={item} size={30} /></span>
    <span className="resource-copy"><strong title={item.name}>{item.name}</strong><span>{item.extension?.toUpperCase() || "文件"} · {formatBytes(item.size)}</span></span>
    <Link className="icon-button" href={href} title={`下载 ${item.name}`}><Download size={18} /></Link>
  </article>;
}

function ShareState({ title, message, siteName, imageUrl }: { title: string; message: string; siteName: string; imageUrl: string }) {
  return <ShareFrame siteName={siteName} imageUrl={imageUrl}><div className="share-state"><KeyRound /><h1>{title}</h1><p>{message}</p><Link href="/">返回首页</Link></div></ShareFrame>;
}

function ShareFrame({ children, siteName, imageUrl }: { children: ReactNode; siteName: string; imageUrl: string }) {
  const background = imageUrl ? ({ "--share-bg": `url("${imageUrl}")` } as CSSProperties) : undefined;
  return <div className="share-page">
    <div className="share-background" style={background} aria-hidden="true" />
    <aside className="share-panel">
      <div className="share-logo"><Brand name={siteName} /></div>
      <main className="share-content">{children}</main>
      <footer className="share-footer">© {new Date().getFullYear()} {siteName} · 安全资源分享</footer>
    </aside>
  </div>;
}
