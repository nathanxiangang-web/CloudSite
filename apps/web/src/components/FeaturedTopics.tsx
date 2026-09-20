import Link from "next/link";
import { ArrowRight, BookOpen } from "lucide-react";

export type TopicEntry = {
  entry_id: string;
  title: string;
  summary: string;
  content_type: string;
  slug: string;
  cover_resource_id: string | null;
};

export function FeaturedTopics({ topics, limit, title }: { topics: TopicEntry[]; limit: number; title: string }) {
  const items = topics.slice(0, limit);
  return <>
    <div className="section-title"><h2>{title}</h2><Link href="/catalog">查看全部 <ArrowRight size={15} /></Link></div>
    {items.length ? (
      <section className="catalog-grid">
        {items.map((entry) => (
          <Link href={`/catalog/${entry.entry_id}`} className="catalog-card" key={entry.entry_id}>
            <span className="catalog-icon"><BookOpen /></span>
            <strong title={entry.title}>{entry.title}</strong>
            <small>{entry.summary || entry.content_type}</small>
          </Link>
        ))}
      </section>
    ) : (
      <div className="empty">还没有发布的专题条目，管理员可在目录管理中发布。</div>
    )}
  </>;
}
