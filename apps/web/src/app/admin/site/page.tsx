"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ImageUp, Save, Trash2 } from "lucide-react";
import Image from "next/image";
import { FormEvent, useState } from "react";
import { AdminShell } from "@/components/AdminShell";
import { api } from "@/lib/api";
import { ShareDuration, SITE_QUERY_KEY } from "@/lib/site";

type SiteSettings = {
  site_name: string;
  home_title: string;
  description: string;
  hero_subtitle: string;
  footer_text: string;
  submission_email: string;
  github_url: string;
  registration_enabled: boolean;
  default_share_duration: ShareDuration;
  share_image_url: string;
};

const initialForm = {
  site_name: "CloudSite",
  home_title: "把网盘变成好看的资源网站",
  description: "",
  hero_subtitle: "",
  footer_text: "",
  submission_email: "",
  github_url: "",
  registration_enabled: true,
  default_share_duration: "24h" as ShareDuration,
};

export default function SitePage() {
  const queryClient = useQueryClient();
  const site = useQuery({ queryKey: ["site"], queryFn: () => api<SiteSettings>("/api/admin/site") });
  const [form, setForm] = useState(initialForm);
  const [image, setImage] = useState<File | null>(null);

  const [syncedSite, setSyncedSite] = useState(site.data);
  if (site.data !== syncedSite) {
    setSyncedSite(site.data);
    if (site.data) setForm({
      site_name: site.data.site_name,
      home_title: site.data.home_title,
      description: site.data.description,
      hero_subtitle: site.data.hero_subtitle,
      footer_text: site.data.footer_text,
      submission_email: site.data.submission_email,
      github_url: site.data.github_url,
      registration_enabled: site.data.registration_enabled,
      default_share_duration: site.data.default_share_duration,
    });
  }

  const save = useMutation({
    mutationFn: () => api("/api/admin/site", { method: "PUT", body: JSON.stringify(form) }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["site"] }),
        queryClient.invalidateQueries({ queryKey: SITE_QUERY_KEY }),
      ]);
    },
  });
  const upload = useMutation({
    mutationFn: (file: File) => {
      const body = new FormData();
      body.set("file", file);
      return api("/api/admin/site/share-image", { method: "POST", body });
    },
    onSuccess: () => {
      setImage(null);
      queryClient.invalidateQueries({ queryKey: ["site"] });
    },
  });
  const remove = useMutation({
    mutationFn: () => api("/api/admin/site/share-image", { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["site"] }),
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  return <AdminShell title="网站设置"><div className="admin-page site-settings-grid">
    <section className="panel">
      <h2>基本信息</h2>
      <form className="form-stack" onSubmit={submit}>
        <label>网站名称<input value={form.site_name} onChange={(event) => setForm({ ...form, site_name: event.target.value })} /></label>
        <label>首页标题<input value={form.home_title} onChange={(event) => setForm({ ...form, home_title: event.target.value })} /></label>
        <label>站点简介<textarea value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} rows={3} /></label>
        <label>首页副标题<input value={form.hero_subtitle} onChange={(event) => setForm({ ...form, hero_subtitle: event.target.value })} /></label>
        <label>页脚文案<input value={form.footer_text} onChange={(event) => setForm({ ...form, footer_text: event.target.value })} /></label>
        <label>投稿邮箱<input type="email" value={form.submission_email} onChange={(event) => setForm({ ...form, submission_email: event.target.value })} /></label>
        <label>GitHub 地址<input type="url" value={form.github_url} onChange={(event) => setForm({ ...form, github_url: event.target.value })} /></label>
        <label>默认分享有效期<select value={form.default_share_duration} onChange={(event) => setForm({ ...form, default_share_duration: event.target.value as ShareDuration })}>
          <option value="5m">5 分钟</option><option value="1h">1 小时</option><option value="6h">6 小时</option><option value="24h">24 小时</option><option value="7d">7 天</option><option value="permanent">永久</option>
        </select></label>
        <label className="checkbox"><input type="checkbox" checked={form.registration_enabled} onChange={(event) => setForm({ ...form, registration_enabled: event.target.checked })} />开放用户自助注册</label>
        <button className="primary" disabled={save.isPending}><Save />{save.isPending ? "正在保存..." : "保存设置"}</button>
        {save.isSuccess && <p className="form-success">已保存，刷新页面即可看到新内容。</p>}
        {save.error && <p className="form-error">{save.error.message}</p>}
      </form>
    </section>

    <section className="panel share-image-settings">
      <h2>分享页图片</h2>
      <p className="panel-intro">用于 PC 分享页整页背景；手机端不会加载。推荐比例 3:2，推荐尺寸 1800×1200 或以上，支持 PNG、JPEG、WebP，最大 8MB。图片将等比铺满整页、允许裁切、不会拉伸。</p>
      <div className={`share-image-preview${site.data?.share_image_url ? " has-image" : ""}`}>
        {site.data?.share_image_url ? <Image src={site.data.share_image_url} alt="当前分享页图片" width={1800} height={1200} unoptimized /> : <span>分享页背景当前留空</span>}
      </div>
      <label className="site-file-input">选择图片<input type="file" accept="image/png,image/jpeg,image/webp" onChange={(event) => setImage(event.target.files?.[0] || null)} /></label>
      <div className="form-actions">
        {site.data?.share_image_url && <button type="button" className="danger" disabled={remove.isPending} onClick={() => remove.mutate()}><Trash2 />移除图片</button>}
        <button type="button" className="primary" disabled={!image || upload.isPending} onClick={() => image && upload.mutate(image)}><ImageUp />{upload.isPending ? "正在上传..." : "上传图片"}</button>
      </div>
      {upload.error && <p className="form-error">{upload.error.message}</p>}
      {remove.error && <p className="form-error">{remove.error.message}</p>}
    </section>
  </div></AdminShell>;
}
