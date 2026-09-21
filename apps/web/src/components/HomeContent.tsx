import Link from "next/link";
import { headers } from "next/headers";
import { Archive, ArrowRight, BookOpen, Clapperboard, Download, File, FileText, FolderTree, Image, PanelsTopLeft, ShieldCheck } from "lucide-react";
import { MobilePrimaryNavigation } from "./PublicNavigation";
import { HomeSearch } from "./HomeSearch";
import { FeaturedCollections } from "./FeaturedCollections";
import { FeaturedTopics, TopicEntry } from "./FeaturedTopics";
import { ContinueSection } from "./ContinueSection";
import { redesignStyles } from "@/features/public-redesign";
import { Collection, formatBytes, Resource } from "@/lib/api";

type BlockType = "featured" | "recent" | "topic" | "category" | "continue";
type OrderedBlock = { type: BlockType; enabled: boolean; sort_order: number; limit: number; title: string };

type HomeData = {
  site: { site_name: string; home_title: string; description: string; hero_subtitle: string };
  counts: Record<string, number>;
  recent: Resource[];
  popular: Resource[];
  collections: Collection[];
  presentation?: {
    enabled: boolean;
    preset: string;
    theme_tokens: { accent_color: string; card_radius: number };
    navigation: { label: string; href: string; sort_order: number }[];
    ordered_blocks: OrderedBlock[];
  };
  topics: TopicEntry[];
  type_entries?: { type: string; display_name: string; count: number; url: string }[];
  popular_strategy?: string;
};

const typeMeta = {
  software: { label: "软件", unit: "个资源", icon: PanelsTopLeft },
  image: { label: "图库", unit: "张图片", icon: Image },
  video: { label: "视频", unit: "个视频", icon: Clapperboard },
  document: { label: "教程", unit: "篇教程", icon: FileText },
  file: { label: "文件", unit: "个文件", icon: File },
} as const;

const BLOCK_LABELS: Record<BlockType, string> = {
  featured: "精选合集",
  recent: "最近更新",
  topic: "推荐专题",
  category: "资源分类",
  continue: "继续使用",
};

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

function CategoryGrid({ counts, title }: { counts: Record<string, number>; title: string }) {
  return <>
    <div className="section-title"><h2>{title}</h2></div>
    <section className="category-grid">
      {(Object.keys(typeMeta) as Array<keyof typeof typeMeta>).slice(0, 4).map((type) => {
        const meta = typeMeta[type];
        const Icon = meta.icon;
        return <Link href={`/browse?type=${type}`} className="category-card" key={type}><span className={`category-icon type-${type}`}><Icon /></span><span><strong>{meta.label}</strong><small>{formatCount(counts[type] ?? 0)} {meta.unit}</small></span><ArrowRight size={18} /></Link>;
      })}
    </section>
  </>;
}

function WhySection() {
  return <section className="why">
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
  </section>;
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
  const topics = data.topics ?? [];

  const presentation = data.presentation;
  const useBlocks = presentation && presentation.enabled && presentation.ordered_blocks && presentation.ordered_blocks.length > 0;

  function renderBlock(block: OrderedBlock) {
    const title = block.title || BLOCK_LABELS[block.type];
    switch (block.type) {
      case "category":
        return <CategoryGrid key={block.type} counts={data.counts} title={title} />;
      case "featured":
        return <div key={block.type}><FeaturedCollections collections={collections} limit={block.limit} title={title} /></div>;
      case "recent":
        return <div key={block.type}><SectionTitle title={title} href="/browse" />
          <section className="recent-table">
            {recent.length ? recent.slice(0, block.limit).map((item) => <RecentRow item={item} key={item.id} />) : <div className="empty">还没有索引数据，请到管理后台配置 AList 并执行同步。</div>}
          </section>
        </div>;
      case "topic":
        return <div key={block.type}><FeaturedTopics topics={topics} limit={block.limit} title={title} /></div>;
      case "continue":
        return <div key={block.type}><SectionTitle title={title} href="/browse" /><ContinueSection limit={block.limit} /></div>;
      default:
        return null;
    }
  }

  return (
    <>
      <section className={redesignStyles.homeHero}>
        <div className={redesignStyles.homeHeroMain}>
          <span className={redesignStyles.eyebrow}>CloudSite 资源平台</span>
          <h1>查找和获取资源</h1>
          <p>{site.hero_subtitle || site.description || "从整理后的资源条目与 CloudSite 文件索引中快速找到需要的内容。"}</p>
          <HomeSearch recent={recent} />
        </div>
        <aside className={redesignStyles.homeHeroAside} aria-label="CloudSite 内容说明">
          <Link href="/catalog" className={redesignStyles.identityCard}>
            <BookOpen />
            <span><strong>已整理的资源条目</strong><small>包含说明、版本、平台与可下载文件，适合确认资源后再选择版本。</small></span>
          </Link>
          <Link href="/resources/software" className={redesignStyles.identityCard}>
            <FolderTree />
            <span><strong>文件与目录索引</strong><small>来自 CloudSite 已完成的资源索引，用于快速浏览刚同步的文件与目录。</small></span>
          </Link>
        </aside>
      </section>

      <MobilePrimaryNavigation />

      <div className={redesignStyles.homeSectionStack}>
      {useBlocks
        ? presentation!.ordered_blocks.map((block) => renderBlock(block))
        : <>
            <FeaturedCollections collections={collections} />
            <CategoryGrid counts={data.counts} title="资源分类" />
            <SectionTitle title="最近更新" href="/browse" />
            <section className="recent-table">
              {recent.length ? recent.slice(0, 6).map((item) => <RecentRow item={item} key={item.id} />) : <div className="empty">还没有索引数据，请到管理后台配置 AList 并执行同步。</div>}
            </section>
            <SectionTitle title="热门资源" href="/browse" />
            <section className="popular-grid">
              {popular ? popular.map((item) => <PopularCard key={item.id} item={item} />) : <div className="empty">暂无热门资源。</div>}
            </section>
          </>}
      </div>

      <WhySection />
    </>
  );
}

export function HomeSkeleton() {
  return (
    <>
      <section className={redesignStyles.homeHero}>
        <div className={redesignStyles.homeHeroMain}>
          <span className={redesignStyles.eyebrow}>CloudSite 资源平台</span>
          <h1 style={{ background: "#eef1f6", color: "transparent", borderRadius: 8, width: "70%" }}>查找和获取资源</h1>
          <p style={{ background: "#eef1f6", color: "transparent", borderRadius: 6, width: "90%", height: 18 }}>软件、图库、视频、教程、文件</p>
          <div className="hero-search" style={{ visibility: "hidden" }}><input /></div>
        </div>
        <div className={redesignStyles.homeHeroAside}>
          <div className={redesignStyles.identityCard} />
          <div className={redesignStyles.identityCard} />
        </div>
      </section>
      <section className="category-grid">
        {Array.from({ length: 4 }).map((_, i) => <div key={i} className="category-card" style={{ background: "#f3f5f9" }} />)}
      </section>
      <div className="section-title"><h2 style={{ background: "#eef1f6", color: "transparent", borderRadius: 6, width: 100, height: 20 }}>精选合集</h2></div>
      <section className="collection-grid">
        {Array.from({ length: 4 }).map((_, i) => <div key={i} className="collection-card" style={{ background: "#f3f5f9" }}><div className="cover" style={{ background: "#eaeef4" }} /><div className="collection-copy" style={{ minHeight: 68 }} /></div>)}
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
