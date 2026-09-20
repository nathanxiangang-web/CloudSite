const RESOURCE_ID_PATTERN = /^[A-Za-z0-9_-]{3,64}$/;

export function collectionCoverSrc(cover: string | null | undefined, fallback: string) {
  const resourceId = cover?.trim() ?? "";
  return RESOURCE_ID_PATTERN.test(resourceId) ? `/p/${resourceId}` : fallback;
}
