export function safeNext(value: string | null | undefined, fallback = "/"): string {
  if (
    !value
    || !value.startsWith("/")
    || value.includes("\\")
    || /[\u0000-\u001f\u007f]/.test(value)
    || /%(?:2f|5c)/i.test(value)
  ) return fallback;
  try {
    const base = new URL("https://cloudsite.invalid");
    const parsed = new URL(value, base);
    if (parsed.origin !== base.origin) return fallback;
    return `${parsed.pathname}${parsed.search}${parsed.hash}`;
  } catch {
    return fallback;
  }
}

const publicAuthPages = new Set(["/login", "/register"]);

function isPublicSharePath(pathname: string): boolean {
  return pathname === "/s" || pathname.startsWith("/s/");
}

export function authRedirectTarget(
  pathname: string,
  search: string,
  authenticated: boolean,
  code: string,
  next: string | null,
): string | null {
  if (publicAuthPages.has(pathname)) {
    return authenticated ? safeNext(next) : null;
  }
  if (isPublicSharePath(pathname)) return null;
  if (authenticated) return null;
  const query = new URLSearchParams({ next: `${pathname}${search}` });
  if (code === "USER_DISABLED") query.set("reason", "disabled");
  return `/login?${query.toString()}`;
}

export function currentRelativeUrl(): string {
  if (typeof window === "undefined") return "/";
  return `${window.location.pathname}${window.location.search}`;
}
