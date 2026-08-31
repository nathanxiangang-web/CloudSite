import { NextRequest, NextResponse } from "next/server";

const apiOrigin = process.env.API_INTERNAL_URL || "http://127.0.0.1:8000";
const publicPages = new Set(["/login", "/register"]);

function safeNext(value: string | null): string {
  if (!value || !value.startsWith("/") || value.startsWith("//") || value.includes("://")) return "/";
  return value;
}

async function hasValidSession(request: NextRequest): Promise<boolean> {
  try {
    const response = await fetch(`${apiOrigin}/api/auth/me`, {
      headers: { cookie: request.headers.get("cookie") || "" },
      cache: "no-store",
    });
    return response.ok;
  } catch {
    return false;
  }
}

export default async function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const authenticated = await hasValidSession(request);
  if (publicPages.has(pathname)) {
    if (!authenticated) return NextResponse.next();
    return NextResponse.redirect(new URL(safeNext(request.nextUrl.searchParams.get("next")), request.url));
  }
  if (authenticated) return NextResponse.next();
  const login = new URL("/login", request.url);
  login.searchParams.set("next", `${pathname}${search}`);
  return NextResponse.redirect(login);
}

export const config = {
  matcher: ["/((?!api|d/|p/|office-files/|admin|_next/static|_next/image|assets/|favicon.ico|icon.svg).*)"],
};
