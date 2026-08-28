"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { Save } from "lucide-react";
import { useEffect, useState } from "react";
import { AdminShell } from "@/components/AdminShell";
import { api } from "@/lib/api";

export default function SitePage() {
  const site = useQuery({ queryKey: ["site"], queryFn: () => api<{ site_name: string; home_title: string; description: string }>("/api/admin/site") });
  const [form, setForm] = useState({ site_name: "CloudSite", home_title: "把网盘变成好看的资源网站", description: "" });
  useEffect(() => { if (site.data) setForm(site.data); }, [site.data]);
  const save = useMutation({ mutationFn: () => api("/api/admin/site", { method: "PUT", body: JSON.stringify(form) }) });
  return <AdminShell title="网站设置"><div className="admin-page narrow"><section className="panel"><h2>基本信息</h2><form className="form-stack" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}><label>网站名称<input value={form.site_name} onChange={(e) => setForm({ ...form, site_name: e.target.value })} /></label><label>首页标题<input value={form.home_title} onChange={(e) => setForm({ ...form, home_title: e.target.value })} /></label><label>网站描述<textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} rows={4} /></label><button className="primary"><Save />保存设置</button>{save.isSuccess && <p className="form-success">已保存，刷新首页即可看到新内容。</p>}</form></section></div></AdminShell>;
}

