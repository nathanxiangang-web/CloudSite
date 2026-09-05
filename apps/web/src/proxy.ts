import { NextRequest, NextResponse } from "next/server";
import { authRedirectTarget } from "./lib/navigation";

const apiOrigin = process.env.API_INTERNAL_URL || "http://127.0.0.1:8000";
const SESSION_COOKIE = "cloudsite_user_session";

type SessionStatus = { authenticated: boolean; code: string };

const UNAUTHENTICATED: SessionStatus = { authenticated: false, code: "" };

async function getSessionStatus(request: NextRequest): Promise<SessionStatus> {
  // 快速路径：无 session cookie 直接判定未登录，省一次后端往返
  if (!request.cookies.has(SESSION_COOKIE)) return UNAUTHENTICATED;
  try {
    const response = await fetch(`${apiOrigin}/api/auth/me`, {
      headers: { cookie: request.headers.get("cookie") || "" },
      cache: "no-store",
    });
    if (response.ok) return { authenticated: true, code: "" };
    const body = await response.json().catch(() => ({}));
    return {
      authenticated: false,
      code: typeof body?.detail?.code === "string" ? body.detail.code : "",
    };
  } catch {
    return UNAUTHENTICATED;
  }
}

export default async function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const session = await getSessionStatus(request);
  const target = authRedirectTarget(
    pathname,
    search,
    session.authenticated,
    session.code,
    request.nextUrl.searchParams.get("next"),
  );
  return target ? NextResponse.redirect(new URL(target, request.url)) : NextResponse.next();
}

export const config = {
  matcher: ["/((?!api|d/|s/.+/d|p/|office-files/|admin|_next/static|_next/image|assets/|favicon.ico|icon.svg).*)"],
};
