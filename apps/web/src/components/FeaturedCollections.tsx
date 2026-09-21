import ImageAsset from "next/image";
import Link from "next/link";
import { ArrowRight, BookOpen, Camera, FolderKanban, Images, PanelsTopLeft, SquarePlay } from "lucide-react";
import { Collection } from "@/lib/api";
import { collectionCoverSrc } from "@/lib/collection-cover";

function formatCount(value: number) {
  return new Intl.NumberFormat("zh-CN").format(value);
}

const fallbackVisuals = [
  { icon: SquarePlay, tone: "blue", cover: "/assets/collection-video.webp" },
  { icon: Camera, tone: "green", cover: "/assets/collection-photography.webp" },
  { icon: Images, tone: "purple", cover: "/assets/collection-image.webp" },
  { icon: PanelsTopLeft, tone: "orange", cover: "/assets/collection-software.webp" },
  { icon: BookOpen, tone: "green", cover: "/assets/collection-2.webp" },
] as const;

function getCollectionVisual(name: string, index: number) {
  if (/视频|video/i.test(name)) return fallbackVisuals[0];
  if (/摄影|photo|camera/i.test(name)) return fallbackVisuals[1];
  if (/图片|图像|图库|image|gallery/i.test(name)) return fallbackVisuals[2];
  if (/软件|应用|software|app/i.test(name)) return fallbackVisuals[3];
  if (/教程|指南|文档|tutorial|guide|document/i.test(name)) return fallbackVisuals[4];
  const fallback = fallbackVisuals[index % fallbackVisuals.length];
  return { icon: FolderKanban, tone: fallback.tone, cover: fallback.cover };
}

export function FeaturedCollections({ collections, limit = 4, title = "精选合集" }: { collections: Collection[]; limit?: number; title?: string }) {
  const featuredCollections = collections.slice(0, limit);

  if (!featuredCollections.length) {
    return <div className="empty">还没有精选合集，管理员可在后台创建。</div>;
  }

  return (
    <section className="featured-collections">
      <div className="collection-heading">
        <div>
          <h2>{title}</h2>
          <p>发现优质资源，探索更多精彩内容</p>
        </div>
        <Link href="/collections">查看全部 <ArrowRight aria-hidden="true" /></Link>
      </div>
      <div className="collection-grid">
        {featuredCollections.map((collection, index) => {
          const visual = getCollectionVisual(collection.name, index);
          const Icon = visual.icon;
          return (
            <Link href={`/collections/${collection.id}`} className="collection-card" key={collection.id}>
              <div className="cover">
                <ImageAsset
                  priority={index === 0}
                  src={collectionCoverSrc(collection.cover, visual.cover)}
                  alt={collection.name}
                  fill
                  sizes="(max-width:767px) 50vw, 25vw"
                />
              </div>
              <div className="collection-copy">
                <span className={`collection-icon ${visual.tone}`}><Icon aria-hidden="true" /></span>
                <span className="collection-text">
                  <strong>{collection.name}</strong>
                  <small>{formatCount(collection.item_count ?? 0)} 个资源</small>
                </span>
                <ArrowRight className="collection-arrow" aria-hidden="true" />
              </div>
            </Link>
          );
        })}
      </div>
    </section>
  );
}
