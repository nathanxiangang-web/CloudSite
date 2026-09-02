"use client";

import { useMutation } from "@tanstack/react-query";
import { Check, Copy, KeyRound, Link2, MousePointerClick, Share2, X } from "lucide-react";
import { FormEvent, useState } from "react";
import { api, Resource, Share } from "@/lib/api";

type Duration = "5m" | "1h" | "6h" | "24h" | "7d" | "permanent";
const durations: Array<[Duration, string]> = [
  ["5m", "5 分钟"],
  ["1h", "1 小时"],
  ["6h", "6 小时"],
  ["24h", "24 小时"],
  ["7d", "7 天"],
  ["permanent", "永久有效"],
];

export function ShareDialog({ resource, onClose }: { resource: Resource; onClose: () => void }) {
  const [accessMode, setAccessMode] = useState<"code" | "direct">("code");
  const [duration, setDuration] = useState<Duration>("24h");
  const [title, setTitle] = useState(resource.name);
  const [copied, setCopied] = useState(false);
  const create = useMutation({
    mutationFn: () => api<Share>("/api/my/shares", {
      method: "POST",
      body: JSON.stringify({ object_type: "resource", object_id: resource.id, title: title.trim(), access_mode: accessMode, duration }),
    }),
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    create.mutate();
  }

  async function copyShare() {
    if (!create.data) return;
    const url = `${window.location.origin}/s/${create.data.token}`;
    const value = create.data.code ? `${url}\n提取码：${create.data.code}` : url;
    await navigator.clipboard.writeText(value);
    setCopied(true);
  }

  return <div className="share-dialog-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
    <section className="share-dialog" role="dialog" aria-modal="true" aria-labelledby="share-dialog-title">
      <button type="button" className="share-dialog-close" aria-label="关闭分享窗口" onClick={onClose}><X /></button>
      {create.data ? <div className="share-dialog-result">
        <span className="share-result-icon"><Check /></span>
        <h2 id="share-dialog-title">分享已创建</h2>
        <p>{create.data.access_mode === "code" ? "复制链接和提取码后发送给对方。" : "打开链接即可直接下载，不需要登录。"}</p>
        <dl>
          <div><dt>分享链接</dt><dd>{`${location.origin}/s/${create.data.token}`}</dd></div>
          {create.data.code && <div><dt>提取码</dt><dd className="share-result-code">{create.data.code}</dd></div>}
        </dl>
        <button type="button" className="primary share-copy-button" onClick={copyShare}>{copied ? <Check /> : <Copy />}{copied ? "已复制" : "复制分享信息"}</button>
      </div> : <>
        <header className="share-dialog-heading"><span><Share2 /></span><div><h2 id="share-dialog-title">分享文件</h2><p title={resource.name}>{resource.name}</p></div></header>
        <form className="share-dialog-form" onSubmit={submit}>
          <fieldset><legend>访问方式</legend><div className="share-mode-control">
            <button type="button" className={accessMode === "code" ? "active" : ""} onClick={() => setAccessMode("code")}><KeyRound />提取码</button>
            <button type="button" className={accessMode === "direct" ? "active" : ""} onClick={() => setAccessMode("direct")}><MousePointerClick />免提取码</button>
          </div></fieldset>
          <label>有效期<select value={duration} onChange={(event) => setDuration(event.target.value as Duration)}>{durations.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <label>分享标题<input value={title} maxLength={200} onChange={(event) => setTitle(event.target.value)} placeholder="输入分享标题" /></label>
          <p className="share-dialog-note"><Link2 />接收者不需要登录 CloudSite{accessMode === "code" ? "，输入 4 位提取码后下载。" : "，打开链接后直接下载。"}</p>
          {create.error && <p className="form-error">{create.error.message}</p>}
          <div className="modal-actions"><button type="button" onClick={onClose}>取消</button><button className="primary" disabled={create.isPending}>{create.isPending ? "正在创建..." : "创建分享"}</button></div>
        </form>
      </>}
    </section>
  </div>;
}
