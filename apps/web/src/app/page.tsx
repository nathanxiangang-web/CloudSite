"use client";

import { useQuery } from "@tanstack/react-query";
import { Archive, ArrowRight, Clapperboard, Download, File, FileImage, FileText, Image, PanelsTopLeft, Search, ShieldCheck } from "lucide-react";
import ImageAsset from "next/image";
import Link from "next/link";
import { FormEvent, useState } from "react";
import { PublicShell } from "@/components/PublicShell";
import { SiteFooter } from "@/components/SiteFooter";
import { api, Collection, formatBytes, Resource } from "@/lib/api";

type HomeData = { site: { site_name: string; home_title: string; description: string }; counts: Record<string, number>; recent: Resource[]; popular: Resource[]; collections: Collection[] };

const typeMeta = {
  software: { label: "软件", unit: "个资源", icon: PanelsTopLeft },
  image: { label: "图片", unit: "张图片", icon: Image },
  video: { label: "视频", unit: "个视频", icon: Clapperboard },
  document: { label: "文档", unit: "个文档", icon: FileText },
  file: { label: "文件", unit: "个文件", icon: File },
} as const;

export default function HomePage() {
  const [query, setQuery] = useState("");
  const { data, isLoading, error } = useQuery({ queryKey: ["home"], queryFn: () => api<HomeData>("/api/home") });
  const submit = (event: FormEvent) => { event.preventDefault(); if (query.trim()) location.href = `/search?q=${encodeURIComponent(query.trim())}`; };
  const site = data?.site ?? { site_name: "CloudSite", home_title: "把网盘变成好看的资源网站", description: "软件、图片、视频、文档、文件，集中管理，轻松搜索，便捷分享" };
  const collections = data?.collections ?? [];
  const popular = data?.popular.length ? data.popular.slice(0, 6) : null;

  return <PublicShell><div className="page home-page">
    <section className="hero">
      <div className="hero-copy"><h1>{site.home_title.slice(0, 7)}<em>{site.home_title.slice(7)}</em></h1><p>{site.description}</p>
        <form className="hero-search" onSubmit={submit}><Search size={21} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索资源、文件夹、标签..." /><button type="submit">搜索</button></form>
        <div className="hot"><span>热门搜索：</span>{["Windows 11", "Photoshop", "Office", "Python", "设计素材", "教程"].map((word) => <Link key={word} href={`/search?q=${encodeURIComponent(word)}`}>{word}</Link>)}</div>
      </div>
      <div className="hero-art"><ImageAsset src="/assets/hero-cloud.png" alt="CloudSite 云端资源插画" fill priority sizes="330px" /></div>
    </section>

    <section className="category-grid">{(Object.keys(typeMeta) as Array<keyof typeof typeMeta>).slice(0, 4).map((type) => { const meta = typeMeta[type]; const Icon = meta.icon; return <Link href={`/resources/${type}`} className="category-card" key={type}><span className={`category-icon type-${type}`}><Icon /></span><span><strong>{meta.label}</strong><small>{formatCount(data?.counts[type] ?? 0)} {meta.unit}</small></span><ArrowRight size={18} /></Link>; })}</section>

    <SectionTitle title="精选合集" href="/collections" />
    {collections.length ? <section className="collection-grid">{collections.map((collection, index) => <Link href={`/collections/${collection.id}`} className="collection-card" key={collection.id}><div className="cover"><ImageAsset src={collection.cover ? `/p/${collection.cover}` : `/assets/collection-${(index % 4) + 1}.png`} alt={collection.name} fill sizes="260px" /></div><strong>{collection.name}</strong><span className="collection-description">{collection.description}</span><div className="collection-meta"><span><FileImage /> {formatCount(collection.item_count ?? 0)} 个资源</span></div></Link>)}</section> : <div className="empty">还没有精选合集，管理员可在后台创建。</div>}

    <SectionTitle title="最近更新" href="/resources/file" />
    <section className="recent-table">{isLoading ? <div className="loading">正在读取资源索引…</div> : error ? <div className="empty error-state">资源索引暂时不可用：{error.message}</div> : data?.recent.length ? data.recent.slice(0, 6).map((item) => <RecentRow item={item} key={item.id} />) : <div className="empty">还没有索引数据，请到管理后台配置 AList 并执行同步。</div>}</section>

    <SectionTitle title="热门资源" href="/resources/file" />
    <section className="popular-grid">{popular ? popular.map((item) => <PopularCard key={item.id} item={item} />) : <div className="empty">暂无热门资源。</div>}</section>

    <section className="why"><h2>为什么选择 CloudSite？</h2><p>让网盘资源管理和分享变得更简单、更高效</p><div>{[
      [Download, "直接下载", "下载请求送入 AList 原生下载链路", "CloudSite 负责校验与跳转", "blue"],
      [Archive, "数据在网盘", "文件存储在您的网盘中", "CloudSite 只负责整理与展示", "green"],
      [PanelsTopLeft, "可视化整理", "管理所选的目录结构", "清晰分类，快速找到需要的资源", "cyan"],
      [ShieldCheck, "安全可靠", "不存储您的文件内容", "保障您的数据隐私与安全", "orange"],
    ].map(([Icon, title, line1, line2, tone]) => <article key={String(title)}><Icon className={`why-icon ${tone}`} /><span><strong>{String(title)}</strong><small>{String(line1)}<br />{String(line2)}</small></span></article>)}</div></section>

    <SiteFooter />
  </div></PublicShell>;
}

function SectionTitle({ title, href }: { title: string; href: string }) { return <div className="section-title"><h2>{title}</h2><Link href={href}>查看全部 <ArrowRight size={15} /></Link></div>; }

function RecentRow({ item }: { item: Resource }) {
  const type = item.content_type in typeMeta ? item.content_type as keyof typeof typeMeta : "file";
  const meta = typeMeta[type]; const Icon = meta.icon;
  return <Link href={`/resource/${item.id}`} className="recent-row"><span className={`recent-icon type-${type}`}><Icon /></span><strong title={item.name}>{item.name}</strong><span className={`type-pill type-${type}`}>{meta.label}</span><span>{formatBytes(item.size)}</span><span>{formatTime(item.modified_at)}</span></Link>;
}

function PopularCard({ item }: { item: Resource }) {
  const safeType = item.content_type in typeMeta ? item.content_type as keyof typeof typeMeta : "file";
  const Icon = typeMeta[safeType].icon;
  return <Link href={`/resource/${item.id}`} className="popular-card"><span className={`popular-icon type-${safeType}`}><Icon /></span><strong title={item.name}>{item.name}</strong><small>{formatBytes(item.size)}</small></Link>;
}

function formatCount(value: number) { return new Intl.NumberFormat("zh-CN").format(value); }
function formatTime(value: string | null) { if (!value) return "刚刚"; const date = new Date(value); if (Number.isNaN(date.getTime())) return "最近"; const hours = Math.max(0, Math.floor((Date.now() - date.getTime()) / 3600000)); if (hours < 1) return "刚刚"; if (hours < 24) return `${hours} 小时前`; if (hours < 48) return `昨天 ${date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false })}`; if (hours < 168) return `${Math.floor(hours / 24)} 天前`; return date.toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" }); }
