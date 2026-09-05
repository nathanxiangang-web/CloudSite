"use client";

import { useMutation } from "@tanstack/react-query";
import { Check, Send } from "lucide-react";
import { FormEvent, useState } from "react";
import { PublicShell } from "@/components/PublicShell";
import { SiteFooter } from "@/components/SiteFooter";
import { useAuth } from "@/lib/auth";
import { api } from "@/lib/api";
import { RESOURCE_TYPES } from "@/lib/submission";

type FormState = {
  resourceName: string;
  resourceType: string;
  description: string;
  sourceUrl: string;
  downloadUrl: string;
  copyrightNote: string;
  note: string;
};

const initialForm: FormState = {
  resourceName: "",
  resourceType: "软件",
  description: "",
  sourceUrl: "",
  downloadUrl: "",
  copyrightNote: "",
  note: "",
};

function isOptionalHttpUrl(value: string) {
  if (!value.trim()) return true;
  return /^https?:\/\//i.test(value.trim());
}

export default function SubmitPage() {
  const auth = useAuth();
  const [form, setForm] = useState(initialForm);
  const update = (key: keyof FormState, value: string) => setForm((current) => ({ ...current, [key]: value }));
  const invalidUrl = !isOptionalHttpUrl(form.sourceUrl) || !isOptionalHttpUrl(form.downloadUrl);
  const incomplete = !form.resourceName.trim() || !form.resourceType || !form.description.trim();
  const notLoggedIn = !auth.data?.authenticated;

  const submit = useMutation({
    mutationFn: () => api("/api/submissions", {
      method: "POST",
      body: JSON.stringify({
        resource_name: form.resourceName,
        resource_type: form.resourceType,
        description: form.description,
        source_url: form.sourceUrl,
        download_url: form.downloadUrl,
        copyright_note: form.copyrightNote,
        note: form.note,
      }),
    }),
    onSuccess: () => { setForm(initialForm); },
  });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (incomplete || invalidUrl || notLoggedIn) return;
    submit.mutate();
  };

  return <PublicShell><div className="page submit-page">
    <header className="submit-hero"><span><Send /></span><div><h1>资源投稿</h1><p>把值得收藏的资源分享给 CloudSite。提交后进入审核队列，通过后会发布到站点。</p></div></header>
    <div className="submit-layout">
      <form className="submit-form" onSubmit={onSubmit}>
        <label>资源名称 *<input required maxLength={120} value={form.resourceName} onChange={(event) => update("resourceName", event.target.value)} placeholder="例如：PotPlayer" /></label>
        <label>资源类型 *<select required value={form.resourceType} onChange={(event) => update("resourceType", event.target.value)}>{RESOURCE_TYPES.map((type) => <option key={type}>{type}</option>)}</select></label>
        <label className="wide">资源简介 *<textarea required maxLength={1000} rows={5} value={form.description} onChange={(event) => update("description", event.target.value)} placeholder="说明资源用途、特点和适用平台" /></label>
        <label>来源网址<input maxLength={1000} inputMode="url" value={form.sourceUrl} onChange={(event) => update("sourceUrl", event.target.value)} placeholder="https://..." /></label>
        <label>下载 / 网盘链接<input maxLength={2000} inputMode="url" value={form.downloadUrl} onChange={(event) => update("downloadUrl", event.target.value)} placeholder="https://..." /></label>
        <label className="wide">版权 / 授权说明<textarea maxLength={1000} rows={3} value={form.copyrightNote} onChange={(event) => update("copyrightNote", event.target.value)} placeholder="公开来源、授权方式或允许转载的说明" /></label>
        <label className="wide">备注<textarea maxLength={1000} rows={3} value={form.note} onChange={(event) => update("note", event.target.value)} placeholder="可补充解压密码、版本或其他注意事项" /></label>
        {invalidUrl && <p className="form-error wide">网址只能使用 http:// 或 https://</p>}
        {notLoggedIn && <p className="form-error wide">请先登录后再投稿。</p>}
        <div className="submit-actions wide"><button className="primary" disabled={incomplete || invalidUrl || submit.isPending || notLoggedIn} type="submit"><Send />{submit.isPending ? "正在提交…" : "提交投稿"}</button></div>
        {submit.isSuccess && <p className="submit-message wide"><Check />投稿已提交，等待审核。可在"我的投稿"查看状态。</p>}
        {submit.error && <p className="form-error wide">{submit.error.message}</p>}
      </form>
      <aside className="submit-aside">
        <h2>站内投稿</h2>
        <p>直接提交到 CloudSite 审核队列，无需打开邮件客户端，也不必复制邮箱。</p>
        <h3>审核流程</h3>
        <p>提交 → 管理员审核 → 通过 / 拒绝 → 发布。审核结果会显示在"我的投稿"。</p>
        <h3>需要提交文件？</h3>
        <p>请填写可访问的网盘 / 下载链接。CloudSite 本身不接收文件上传，开发成本和风险都可控。</p>
      </aside>
    </div>
    <section className="submit-notice"><strong>提交前请确认</strong><p>投稿仅代表提交审核，不代表资源一定收录或立即发布。请仅投稿你有权分享、公开来源明确或允许转载的资源；请勿提交密码、身份证件、私密文件、侵权内容、违法内容或恶意程序。</p></section>
    <SiteFooter />
  </div></PublicShell>;
}
