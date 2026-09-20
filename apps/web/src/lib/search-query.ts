export const SEARCH_QUERY_MAX_LENGTH = 200;

export function normalizeSearchQuery(value: string): string {
  return value.trim().replace(/\s+/g, " ").slice(0, SEARCH_QUERY_MAX_LENGTH);
}
