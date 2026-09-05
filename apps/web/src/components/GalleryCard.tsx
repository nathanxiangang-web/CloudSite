"use client";

import { Image } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { Resource } from "@/lib/api";

export function GalleryCard({ item }: { item: Resource }) {
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState(false);
  const src = item.thumbnail || `/p/${item.id}`;
  return (
    <Link href={`/resource/${item.id}`} className="gallery-card" aria-label={item.name}>
      <span className="gallery-thumb">
        {!loaded && !error && <span className="gallery-thumb-skeleton" aria-hidden="true" />}
        {error ? (
          <span className="gallery-thumb-error"><Image size={26} /><small>图片加载失败</small></span>
        ) : (
          <img src={src} alt={item.name} loading="lazy" onLoad={() => setLoaded(true)} onError={() => setError(true)} />
        )}
      </span>
      <span className="gallery-copy">
        <strong title={item.name}>{item.name}</strong>
        <small>{item.extension?.toUpperCase() || "图片"}</small>
      </span>
    </Link>
  );
}
