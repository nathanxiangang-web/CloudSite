import ImageAsset from "next/image";
import Link from "next/link";
import { ArrowRight, BookOpen, FolderKanban, Images, PanelsTopLeft, SquarePlay } from "lucide-react";
import { Collection } from "@/lib/api";
import { collectionCoverSrc } from "@/lib/collection-cover";

function formatCount(value: number) {
  return new Intl.NumberFormat("zh-CN").format(value);
}

const featuredRules = [
  {
    test: /软件|应用|software|app/i,
    visual: { icon: PanelsTopLeft, tone: "orange", cover: "/assets/collection-software.webp" },
  },
  {
    test: /视频|video/i,
    visual: { icon: SquarePlay, tone: "blue", cover: "/assets/collection-video.webp" },
  },
  {
    test: /图片|图像|图库|摄影|image|gallery|photo|camera/i,
    visual: { icon: Images, tone: "purple", cover: "/assets/collection-image.webp" },
  },
  {
    test: /教程|课程|学习|教学|tutorial|course|learn/i,
    visual: { icon: BookOpen, tone: "green", cover: "/assets/collection-tutorial.webp" },
  },
] as const;

const fallbackVisuals = featuredRules.map((rule) => rule.visual);

function getCollectionVisual(name: string, index: number) {
  const matched = featuredRules.find((rule) => rule.test.test(name));
  if (matched) return matched.visual;
  const fallback = fallbackVisuals[index % fallbackVisuals.length];
  return { icon: FolderKanban, tone: fallback.tone, cover: fallback.cover };
}

function selectFeaturedCollections(collections: Collection[]) {
  const selected: Collection[] = [];
  const selectedIds = new Set<number>();

  for (const rule of featuredRules) {
    const match = collections.find(
      (collection) => !selectedIds.has(collection.id) && rule.test.test(collection.name),
    );
    if (match) {
      selected.push(match);
      selectedIds.add(match.id);
    }
  }

  for (const collection of collections) {
    if (selected.length >= 4) break;
    if (!selectedIds.has(collection.id)) {
      selected.push(collection);
      selectedIds.add(collection.id);
    }
  }

  return selected.slice(0, 4);
}

export function FeaturedCollections({ collections }: { collections: Collection[] }) {
  const featuredCollections = selectFeaturedCollections(collections);

  if (!featuredCollections.length) {
    return <div className="empty">还没有精选合集，管理员可在后台创建。</div>;
  }

  return (
    <section className="featured-collections">
      <div className="collection-heading">
        <div>
          <h2>精选合集</h2>
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
