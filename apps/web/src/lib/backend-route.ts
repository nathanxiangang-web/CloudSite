export function backendPathFor(pathname: string): string | null {
  if (pathname === "/api" || pathname.startsWith("/api/")) return pathname;
  if (pathname === "/d" || pathname.startsWith("/d/")) return pathname;
  if (pathname === "/p" || pathname.startsWith("/p/")) return pathname;
  if (pathname === "/office-files" || pathname.startsWith("/office-files/")) return pathname;

  const shareVerify = pathname.match(/^\/s\/([^/]+)\/verify$/);
  if (shareVerify) return `/api/public/shares/${shareVerify[1]}/verify`;

  const shareContent = pathname.match(/^\/s\/([^/]+)\/content$/);
  if (shareContent) return `/api/public/shares/${shareContent[1]}/content`;

  if (/^\/s\/[^/]+\/d(?:\/.*)?$/.test(pathname)) return pathname;

  return null;
}
