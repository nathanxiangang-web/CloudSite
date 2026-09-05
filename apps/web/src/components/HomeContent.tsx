import ImageAsset from "next/image";
import Link from "next/link";
import { headers } from "next/headers";
import { Archive, ArrowRight, Clapperboard, Download, File, FileImage, FileText, Image, PanelsTopLeft, ShieldCheck } from "lucide-react";
import { MobilePrimaryNavigation } from "./PublicNavigation";
import { HomeSearch } from "./HomeSearch";
import { Collection, formatBytes, Resource } from "@/lib/api";

type HomeData = {
  site: { site_name: string; home_title: string; description: string; hero_subtitle: string };
  counts: Record<string, number>;
  recent: Resource[];
  popular: Resource[];
  collections: Collection[];
};

const typeMeta = {
  software: { label: "软件", unit: "个资源", icon: PanelsTopLeft },
  image: { label: "图库", unit: "张图片", icon: Image },
  video: { label: "视频", unit: "个视频", icon: Clapperboard },
  document: { label: "教程", unit: "篇教程", icon: FileText },
  file: { label: "文件", unit: "个文件", icon: File },
} as const;

function formatCount(value: number) {
  return new Intl.NumberFormat("zh-CN").format(value);
}

function formatTime(value: string | null) {
  if (!value) return "刚刚";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "最近";
  const hours = Math.max(0, Math.floor((Date.now() - date.getTime()) / 3600000));
  if (hours < 1) return "刚刚";
  if (hours < 24) return `${hours} 小时前`;
  if (hours < 48) return `昨天 ${date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false })}`;
  if (hours < 168) return `${Math.floor(hours / 24)} 天前`;
  return date.toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" });
}

function SectionTitle({ title, href }: { title: string; href: string }) {
  return <div className="section-title"><h2>{title}</h2><Link href={href}>查看全部 <ArrowRight size={15} /></Link></div>;
}

function RecentRow({ item }: { item: Resource }) {
  const type = item.content_type in typeMeta ? (item.content_type as keyof typeof typeMeta) : "file";
  const meta = typeMeta[type];
  const Icon = meta.icon;
  return <Link href={`/resource/${item.id}`} className="recent-row"><span className={`recent-icon type-${type}`}><Icon /></span><strong title={item.name}>{item.name}</strong><span className={`type-pill type-${type}`}>{meta.label}</span><span>{formatBytes(item.size)}</span><span>{formatTime(item.modified_at)}</span></Link>;
}

function PopularCard({ item }: { item: Resource }) {
  const safeType = item.content_type in typeMeta ? (item.content_type as keyof typeof typeMeta) : "file";
  const Icon = typeMeta[safeType].icon;
  return <Link href={`/resource/${item.id}`} className="popular-card"><span className={`popular-icon type-${safeType}`}><Icon /></span><strong title={item.name}>{item.name}</strong><small>{formatBytes(item.size)}</small></Link>;
}

export async function HomeContent() {
  const apiBase = process.env.API_INTERNAL_URL || "http://127.0.0.1:8000";
  const headerList = await headers();
  const cookie = headerList.get("cookie") || "";
  const response = await fetch(`${apiBase}/api/home`, { headers: { cookie }, next: { revalidate: 60 } });
  if (!response.ok) throw new Error(`首页数据不可用 (${response.status})`);
  const data: HomeData = await response.json();

  const site = data.site ?? { site_name: "CloudSite", home_title: "把网盘变成好看的资源网站", description: "软件、图库、视频、教程和文件，集中整理，轻松搜索，便捷分享", hero_subtitle: "" };
  const collections = data.collections ?? [];
  const popular = data.popular.length ? data.popular.slice(0, 6) : null;
  const recent = data.recent ?? [];
  const accent = "资源网站";
  const titleLead = site.home_title.endsWith(accent) ? site.home_title.slice(0, -accent.length) : site.home_title;
  const titleAccent = site.home_title.endsWith(accent) ? accent : "";

  return (
    <>
      <section className="hero">
        <div className="hero-copy">
          <h1><span>{titleLead}</span>{titleAccent && <em>{titleAccent}</em>}</h1>
          <p>{site.hero_subtitle || site.description}</p>
          <HomeSearch recent={recent} />
        </div>
        <div className="hero-art">
          <ImageAsset className="hero-img-light" src="/assets/hero-cloud.webp" alt="CloudSite 云端资源插画" fill priority sizes="330px" />
          <ImageAsset className="hero-img-dark" src="/assets/hero-cloud-dark.webp" alt="CloudSite 云端资源插画" fill sizes="330px" />
        </div>
      </section>

      <MobilePrimaryNavigation />

      <section className="category-grid">
        {(Object.keys(typeMeta) as Array<keyof typeof typeMeta>).slice(0, 4).map((type) => {
          const meta = typeMeta[type];
          const Icon = meta.icon;
          return <Link href={`/resources/${type}`} className="category-card" key={type}><span className={`category-icon type-${type}`}><Icon /></span><span><strong>{meta.label}</strong><small>{formatCount(data.counts[type] ?? 0)} {meta.unit}</small></span><ArrowRight size={18} /></Link>;
        })}
      </section>

      <SectionTitle title="精选合集" href="/collections" />
      {collections.length ? (
        <section className="collection-grid">
          {collections.map((collection, index) => (
            <Link href={`/collections/${collection.id}`} className="collection-card" key={collection.id}>
              <div className="cover">
                <ImageAsset priority={index === 0} src={collection.cover ? `/p/${collection.cover}` : `/assets/collection-${(index % 4) + 1}.webp`} alt={collection.name} fill sizes="(max-width:768px) 50vw, 25vw" />
              </div>
              <strong>{collection.name}</strong>
              <span className="collection-description">{collection.description}</span>
              <div className="collection-meta"><span><FileImage /> {formatCount(collection.item_count ?? 0)} 个资源</span></div>
            </Link>
          ))}
        </section>
      ) : <div className="empty">还没有精选合集，管理员可在后台创建。</div>}

      <SectionTitle title="最近更新" href="/resources/file" />
      <section className="recent-table">
        {recent.length ? recent.slice(0, 6).map((item) => <RecentRow item={item} key={item.id} />) : <div className="empty">还没有索引数据，请到管理后台配置 AList 并执行同步。</div>}
      </section>

      <SectionTitle title="热门资源" href="/resources/file" />
      <section className="popular-grid">
        {popular ? popular.map((item) => <PopularCard key={item.id} item={item} />) : <div className="empty">暂无热门资源。</div>}
      </section>

      <section className="why">
        <h2>为什么选择 CloudSite？</h2>
        <p>让网盘资源管理和分享变得更简单、更高效</p>
        <div>
          {([
            [Download, "直接下载", "下载请求送入 AList 原生下载链路", "CloudSite 负责校验与跳转", "blue"],
            [Archive, "数据在网盘", "文件存储在您的网盘中", "CloudSite 只负责整理与展示", "green"],
            [PanelsTopLeft, "可视化整理", "管理所选的目录结构", "清晰分类，快速找到需要的资源", "cyan"],
            [ShieldCheck, "安全可靠", "不存储您的文件内容", "保障您的数据隐私与安全", "orange"],
          ] as const).map(([Icon, title, line1, line2, tone]) => (
            <article key={String(title)}><Icon className={`why-icon ${tone}`} /><span><strong>{String(title)}</strong><small>{String(line1)}<br />{String(line2)}</small></span></article>
          ))}
        </div>
      </section>
    </>
  );
}

export function HomeSkeleton() {
  return (
    <>
      <section className="hero">
        <div className="hero-copy">
          <h1 style={{ background: "#eef1f6", color: "transparent", borderRadius: 8, width: "70%" }}>把网盘变成好看的资源网站</h1>
          <p style={{ background: "#eef1f6", color: "transparent", borderRadius: 6, width: "90%", height: 18 }}>软件、图库、视频、教程、文件</p>
          <div className="hero-search" style={{ visibility: "hidden" }}><input /></div>
        </div>
        <div className="hero-art" style={{ background: "#eef1f6", borderRadius: 12 }} />
      </section>
      <section className="category-grid">
        {Array.from({ length: 4 }).map((_, i) => <div key={i} className="category-card" style={{ background: "#f3f5f9" }} />)}
      </section>
      <div className="section-title"><h2 style={{ background: "#eef1f6", color: "transparent", borderRadius: 6, width: 100, height: 20 }}>精选合集</h2></div>
      <section className="collection-grid">
        {Array.from({ length: 4 }).map((_, i) => <div key={i} className="collection-card" style={{ background: "#f3f5f9" }}><div className="cover" style={{ background: "#eaeef4" }} /></div>)}
      </section>
      <div className="section-title"><h2 style={{ background: "#eef1f6", color: "transparent", borderRadius: 6, width: 100, height: 20 }}>最近更新</h2></div>
      <section className="recent-table">
        {Array.from({ length: 5 }).map((_, i) => <div key={i} className="recent-row" style={{ background: "#f3f5f9", height: 52, borderRadius: 8 }} />)}
      </section>
      <div className="section-title"><h2 style={{ background: "#eef1f6", color: "transparent", borderRadius: 6, width: 100, height: 20 }}>热门资源</h2></div>
      <section className="popular-grid">
        {Array.from({ length: 6 }).map((_, i) => <div key={i} className="popular-card" style={{ background: "#f3f5f9" }} />)}
      </section>
    </>
  );
}
