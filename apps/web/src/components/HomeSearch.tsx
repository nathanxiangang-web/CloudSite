"use client";

import { Search } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { normalizeSearchQuery, SEARCH_QUERY_MAX_LENGTH } from "@/lib/search-query";
import { Resource } from "@/lib/api";

export function HomeSearch({ recent }: { recent: Resource[] }) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const normalized = normalizeSearchQuery(query);
    if (normalized) router.push(`/search?q=${encodeURIComponent(normalized)}`);
  };
  return (
    <>
      <form className="hero-search" onSubmit={submit}>
        <Search size={21} />
        <input maxLength={SEARCH_QUERY_MAX_LENGTH} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索资源、文件夹、标签..." />
        <button type="submit">搜索</button>
      </form>
      <div className="hot">
        <span>热门搜索：</span>
        {recent.slice(0, 6).map((item) => {
          const keyword = item.name.replace(/\.[^.]+$/, "").slice(0, 20);
          return <Link key={item.id} href={`/search?q=${encodeURIComponent(keyword)}`}>{keyword}</Link>;
        })}
      </div>
    </>
  );
}
