import { api } from "@/lib/api";
import { buildCatalogEntriesQuery, buildCatalogSearchQuery } from "./model";
import type {
  CatalogEntryDetail,
  CatalogEntrySummary,
  CatalogPage,
  CatalogReleaseDetail,
  CatalogSearchResponse,
  CatalogTag,
} from "./types";

export async function fetchCatalogEntries(params: {
  page?: number;
  page_size?: number;
  content_type?: string;
  tag?: string;
} = {}): Promise<CatalogPage<CatalogEntrySummary>> {
  return api<CatalogPage<CatalogEntrySummary>>(buildCatalogEntriesQuery(params));
}

export async function fetchCatalogSearch(params: {
  q: string;
  page?: number;
  page_size?: number;
  content_type?: string;
  tag?: string;
  platform?: string;
}): Promise<CatalogSearchResponse> {
  return api<CatalogSearchResponse>(buildCatalogSearchQuery(params));
}

export async function fetchCatalogTags(): Promise<{ items: CatalogTag[] }> {
  return api<{ items: CatalogTag[] }>("/api/catalog/tags");
}

export async function fetchCatalogEntry(
  entryId: string,
): Promise<CatalogEntryDetail> {
  return api<CatalogEntryDetail>(
    `/api/catalog/entries/${encodeURIComponent(entryId)}`,
  );
}

export async function fetchCatalogRelease(
  releaseId: string,
): Promise<CatalogReleaseDetail> {
  return api<CatalogReleaseDetail>(
    `/api/catalog/releases/${encodeURIComponent(releaseId)}`,
  );
}

