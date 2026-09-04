"use client";

import { Check, Clipboard, ExternalLink, Mail, Send } from "lucide-react";
import { FormEvent, useMemo, useState } from "react";
import { PublicShell } from "@/components/PublicShell";
import { SiteFooter } from "@/components/SiteFooter";
import { useAuth } from "@/lib/auth";
import { buildSubmission, isOptionalHttpUrl, RESOURCE_TYPES, SUBMISSION_EMAIL } from "@/lib/submission";
import { useSite } from "@/lib/site";

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

export default function SubmitPage() {
  const auth = useAuth();
  const site = useSite();
  const [form, setForm] = useState(initialForm);
  const [message, setMessage] = useState("");
  const username = auth.data?.user?.username || "";
  const submissionEmail = site.submission_email || SUBMISSION_EMAIL;
  const submission = useMemo(() => buildSubmission({ ...form, username }, submissionEmail), [form, username, submissionEmail]);
  const invalidUrl = !isOptionalHttpUrl(form.sourceUrl) || !isOptionalHttpUrl(form.downloadUrl);
  const incomplete = !form.resourceName.trim() || !form.resourceType || !form.description.trim();

  const update = (key: keyof FormState, value: string) => setForm((current) => ({ ...current, [key]: value }));
  const copy = async (value: string, success: string) => {
    try {
      await navigator.clipboard.writeText(value);
      setMessage(success);
    } catch {
      setMessage("复制失败，请手动选择并复制下方内容");
    }
  };
  const openMail = (event: FormEvent) => {
    event.preventDefault();
    if (incomplete || invalidUrl) return;
    window.location.href = submission.mailto;
  };

  return <PublicShell><div className="page submit-page">
    <header className="submit-hero"><span><Send /></span><div><h1>资源投稿</h1><p>把值得收藏的资源分享给 CloudSite。我们会人工检查来源、安全性和版权信息。</p></div></header>
    <div className="submit-layout">
      <form className="submit-form" onSubmit={openMail}>
        <label>资源名称 *<input required maxLength={120} value={form.resourceName} onChange={(event) => update("resourceName", event.target.value)} placeholder="例如：PotPlayer" /></label>
        <label>资源类型 *<select required value={form.resourceType} onChange={(event) => update("resourceType", event.target.value)}>{RESOURCE_TYPES.map((type) => <option key={type}>{type}</option>)}</select></label>
        <label className="wide">资源简介 *<textarea required maxLength={1000} rows={5} value={form.description} onChange={(event) => update("description", event.target.value)} placeholder="说明资源用途、特点和适用平台" /></label>
        <label>来源网址<input maxLength={1000} inputMode="url" value={form.sourceUrl} onChange={(event) => update("sourceUrl", event.target.value)} placeholder="https://..." /></label>
        <label>下载 / 网盘链接<input maxLength={2000} inputMode="url" value={form.downloadUrl} onChange={(event) => update("downloadUrl", event.target.value)} placeholder="https://..." /></label>
        <label className="wide">版权 / 授权说明<textarea maxLength={1000} rows={3} value={form.copyrightNote} onChange={(event) => update("copyrightNote", event.target.value)} placeholder="公开来源、授权方式或允许转载的说明" /></label>
        <label className="wide">备注<textarea maxLength={1000} rows={3} value={form.note} onChange={(event) => update("note", event.target.value)} placeholder="可补充解压密码、版本或其他注意事项" /></label>
        {invalidUrl && <p className="form-error wide">网址只能使用 http:// 或 https://</p>}
        <div className="submit-actions wide"><button type="button" onClick={() => copy(submission.body, "投稿内容已复制")}><Clipboard />复制投稿内容</button><button className="primary" disabled={incomplete || invalidUrl} type="submit"><Mail />打开邮箱投稿</button></div>
        {message && <p className="submit-message wide"><Check />{message}</p>}
      </form>
      <aside className="submit-aside">
        <h2>投稿邮箱</h2>
        <button className="copy-email" type="button" onClick={() => copy(submissionEmail, "投稿邮箱已复制")}><strong>{submissionEmail}</strong><Clipboard /></button>
        <p>“打开邮箱投稿”只会调用你设备上的默认邮件客户端。CloudSite 不连接 Outlook SMTP，也不保存邮箱密码。</p>
        <h3>没有配置邮件客户端？</h3>
        <p>复制邮箱和投稿内容，再自行打开 Outlook、Gmail、QQ 邮箱或其他邮箱粘贴发送。</p>
        <h3>需要提交文件？</h3>
        <p>请在邮件客户端手动添加附件，或填写可访问的网盘 / 下载链接。CloudSite 本身不接收上传。</p>
        <a href={submission.mailto}><ExternalLink />预览邮件链接</a>
      </aside>
    </div>
    <section className="submit-notice"><strong>提交前请确认</strong><p>投稿仅代表提交审核，不代表资源一定收录或立即发布。请仅投稿你有权分享、公开来源明确或允许转载的资源；请勿提交密码、身份证件、私密文件、侵权内容、违法内容或恶意程序。</p></section>
    <SiteFooter />
  </div></PublicShell>;
}
