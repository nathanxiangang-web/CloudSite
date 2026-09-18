import { request, expect, type APIRequestContext } from '@playwright/test';

/**
 * Common E2E helpers for CloudSite.
 *
 * All helpers are defensive: they never throw on connection failures,
 * returning sentinel values instead so callers can skip tests cleanly.
 */

const WEB_BASE_URL = process.env.E2E_WEB_URL ?? 'http://localhost:3000';
const API_BASE_URL = process.env.E2E_API_URL ?? 'http://localhost:8000';

export type ApiHealth = {
  ok: boolean;
  reason?: string;
  baseUrl: string;
  version?: string;
};

/**
 * Probe the API health endpoint. Resolves quickly when the server is down
 * so the test suite can skip instead of hanging.
 */
export async function waitForApiReady(timeoutMs = 5_000): Promise<ApiHealth> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${API_BASE_URL}/api/health`, {
      signal: controller.signal,
    });
    if (!res.ok) {
      return { ok: false, reason: `health status ${res.status}`, baseUrl: API_BASE_URL };
    }
    const body = await res.json().catch(() => ({}));
    return {
      ok: true,
      baseUrl: API_BASE_URL,
      version: typeof body.version === 'string' ? body.version : undefined,
    };
  } catch (err) {
    return {
      ok: false,
      reason: err instanceof Error ? err.message : 'fetch failed',
      baseUrl: API_BASE_URL,
    };
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Probe the web app root. Returns true when the server responds with HTML.
 */
export async function waitForWebReady(timeoutMs = 5_000): Promise<boolean> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(WEB_BASE_URL, { signal: controller.signal });
    return res.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Attempt to log in via the API and return an authenticated request context.
 * Returns null on any failure so the caller can skip the test.
 */
export async function loginViaApi(
  health: ApiHealth,
  credentials?: { username: string; password: string },
): Promise<APIRequestContext | null> {
  if (!health.ok) return null;
  const creds = credentials ?? {
    username: process.env.E2E_USER ?? 'e2e_user',
    password: process.env.E2E_PASS ?? 'e2e_pass_123',
  };
  try {
    const ctx = await request.newContext({ baseURL: health.baseUrl });
    const res = await ctx.post('/api/auth/login', { data: creds });
    if (!res.ok()) {
      // Try register first, then login (test user may not exist yet).
      const reg = await ctx.post('/api/auth/register', { data: creds });
      if (!reg.ok()) return null;
      const login2 = await ctx.post('/api/auth/login', { data: creds });
      if (!login2.ok()) return null;
    }
    return ctx;
  } catch {
    return null;
  }
}

/**
 * Navigate to a path and wait for the page to be ready (networkidle-ish).
 * Fails the test if navigation throws, but only after the skip gates pass.
 */
export async function navigateTo(page: import('@playwright/test').Page, path: string): Promise<void> {
  await page.goto(path, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle').catch(() => {});
}

/**
 * Log in through the web UI. Assumes the /login route exists.
 */
export async function loginViaUi(
  page: import('@playwright/test').Page,
  credentials?: { username: string; password: string },
): Promise<void> {
  const creds = credentials ?? {
    username: process.env.E2E_USER ?? 'e2e_user',
    password: process.env.E2E_PASS ?? 'e2e_pass_123',
  };
  await navigateTo(page, '/login');
  const userInput = page.locator('input[autocomplete="username"], input[name="username"], input[name="email"], input[type="email"]').first();
  const passInput = page.locator('input[type="password"], input[name="password"]').first();
  await userInput.fill(creds.username);
  await passInput.fill(creds.password);
  const submit = page.locator('button.user-auth-submit, button[type="submit"], button:has-text("登录"), button:has-text("Login"), button:has-text("Sign in")').first();
  await submit.click();
  await page.waitForURL((url) => !url.pathname.includes('/login'), { timeout: 15_000 }).catch(() => {});
}

/**
 * Register a new user through the web UI. Assumes /register route exists.
 */
export async function registerViaUi(
  page: import('@playwright/test').Page,
  credentials?: { username: string; password: string; email?: string },
): Promise<void> {
  const creds = credentials ?? {
    username: `e2e_${Date.now()}`,
    password: 'e2e_pass_123',
    email: `e2e_${Date.now()}@example.test`,
  };
  await navigateTo(page, '/register');
  const userInput = page.locator('input[autocomplete="username"], input[name="username"]').first();
  const emailInput = page.locator('input[name="email"], input[type="email"]').first();
  const passInputs = page.locator('input[type="password"], input[name="password"]');
  await userInput.fill(creds.username);
  if (await emailInput.count() > 0) {
    await emailInput.fill(creds.email ?? `${creds.username}@example.test`);
  }
  const passCount = await passInputs.count();
  await passInputs.nth(0).fill(creds.password);
  if (passCount > 1) {
    await passInputs.nth(1).fill(creds.password);
  }
  const submit = page.locator('button.user-auth-submit, button[type="submit"], button:has-text("创建账号"), button:has-text("Register"), button:has-text("Sign up")').first();
  await submit.click();
  await page.waitForURL((url) => !url.pathname.includes('/register'), { timeout: 15_000 }).catch(() => {});
}

/**
 * Log out via the web UI. Looks for a logout link/button or visits /logout.
 */
export async function logoutViaUi(page: import('@playwright/test').Page): Promise<void> {
  const logoutBtn = page.locator('button:has-text("退出登录"), button:has-text("Logout"), button:has-text("Log out")').first();
  const detailsSummary = page.locator('details.auth-menu > summary').first();
  if ((await detailsSummary.count()) > 0) {
    await detailsSummary.click().catch(() => {});
    await page.waitForTimeout(500);
  }
  const btnCount = await logoutBtn.count();
  if (btnCount > 0) {
    await logoutBtn.click({ force: true }).catch(() => {});
  }
  await page.evaluate(async () => {
    try { await fetch('/api/auth/logout', { method: 'POST' }); } catch {}
    window.location.href = '/login';
  }).catch(() => {});
  await page.waitForURL((url) => url.pathname.includes('/login'), { timeout: 10_000 }).catch(() => {});
  await page.waitForLoadState('domcontentloaded').catch(() => {});
  await page.waitForTimeout(500);
}

/**
 * Check whether the current page shows an authenticated state (e.g. user
 * menu, logout button, or absence of login link).
 */
export async function isAuthenticated(page: import('@playwright/test').Page): Promise<boolean> {
  if (page.url().includes('/login') || page.url().includes('/register')) return false;
  await page.waitForTimeout(500);
  const authMenu = page.locator('details.auth-menu').first();
  const logout = page.locator('button:has-text("退出登录"), a:has-text("退出登录"), button:has-text("Logout"), [data-testid="user-menu"]').first();
  const login = page.locator('nav.auth-links a:has-text("登录"), a:has-text("Login"), a:has-text("Sign in")').first();
  if ((await authMenu.count()) > 0) return true;
  if ((await logout.count()) > 0) return true;
  if ((await login.count()) > 0) return false;
  return false;
}

/**
 * Wait for a specific API route to respond on the page (useful for
 * confirming data fetches completed).
 */
export async function waitForApiResponse(
  page: import('@playwright/test').Page,
  urlPattern: string | RegExp,
  timeoutMs = 10_000,
): Promise<void> {
  await page
    .waitForResponse((res) => {
      const url = res.url();
      const match = typeof urlPattern === 'string' ? url.includes(urlPattern) : urlPattern.test(url);
      return match && res.ok();
    }, { timeout: timeoutMs })
    .catch(() => {});
}

/**
 * Generate a unique test resource name.
 */
export function uniqueName(prefix = 'e2e'): string {
  return `${prefix}_${Date.now()}_${Math.floor(Math.random() * 1000)}`;
}

export { WEB_BASE_URL, API_BASE_URL };
export { expect };