import { test, expect } from './fixtures';
import { navigateTo, waitForApiResponse } from './helpers';

/**
 * B5-07 Admin flow.
 *
 * Covers: admin login -> user management -> content root -> diagnostics.
 * Tests skip when the API is not running or admin credentials are not
 * provided via environment variables.
 */

const ADMIN_USER = process.env.E2E_ADMIN_USER ?? 'admin';
const ADMIN_PASS = process.env.E2E_ADMIN_PASS ?? 'admin';

test.describe('07 - Admin', () => {
  test('admin login page loads', async ({ page, webReady, apiHealth }) => {
    test.skip(!webReady || !apiHealth.ok, 'web or API not ready');
    await navigateTo(page, '/admin/login');
    const body = page.locator('body');
    await expect(body).toBeVisible();
    const userInput = page.locator('input[name="username"], input[name="email"], input[type="email"]').first();
    await expect(userInput).toBeVisible();
  });

  test('admin can log in', async ({ page, webReady, apiHealth }) => {
    test.skip(!webReady || !apiHealth.ok, 'web or API not ready');
    await navigateTo(page, '/admin/login');
    const userInput = page.locator('input[name="username"], input[name="email"], input[type="email"]').first();
    const passInput = page.locator('input[name="password"], input[type="password"]').first();
    await userInput.fill(ADMIN_USER);
    await passInput.fill(ADMIN_PASS);
    const submit = page.locator('button[type="submit"]').first();
    await submit.click();
    await page.waitForURL((url) => !url.pathname.includes('/login'), { timeout: 15_000 }).catch(() => {});
    // Should be redirected to admin dashboard.
    expect(page.url()).toContain('/admin');
    expect(page.url()).not.toContain('/login');
  });

  test('admin dashboard loads', async ({ page, webReady, apiHealth }) => {
    test.skip(!webReady || !apiHealth.ok, 'web or API not ready');
    await navigateTo(page, '/admin/login');
    const userInput = page.locator('input[name="username"], input[name="email"], input[type="email"]').first();
    const passInput = page.locator('input[name="password"], input[type="password"]').first();
    await userInput.fill(ADMIN_USER);
    await passInput.fill(ADMIN_PASS);
    const submit = page.locator('button[type="submit"]').first();
    await submit.click();
    await page.waitForURL((url) => !url.pathname.includes('/login'), { timeout: 15_000 }).catch(() => {});
    const body = page.locator('body');
    await expect(body).toBeVisible();
    // Dashboard should have some admin navigation.
    const adminNav = page.locator('a[href*="/admin/"]').first();
    const navCount = await adminNav.count();
    expect(navCount).toBeGreaterThan(0);
  });

  test('user management page loads', async ({ page, webReady, apiHealth }) => {
    test.skip(!webReady || !apiHealth.ok, 'web or API not ready');
    await navigateTo(page, '/admin/login');
    const userInput = page.locator('input[name="username"], input[name="email"], input[type="email"]').first();
    const passInput = page.locator('input[name="password"], input[type="password"]').first();
    await userInput.fill(ADMIN_USER);
    await passInput.fill(ADMIN_PASS);
    const submit = page.locator('button[type="submit"]').first();
    await submit.click();
    await page.waitForURL((url) => !url.pathname.includes('/login'), { timeout: 15_000 }).catch(() => {});
    await navigateTo(page, '/admin/users');
    await waitForApiResponse(page, /\/api\//);
    const body = page.locator('body');
    await expect(body).toBeVisible();
    // User list should have a table or list of users.
    const userList = page.locator('table, [data-testid="user-list"], .user-list, ul').first();
    await expect(userList).toBeVisible();
  });

  test('content root / catalog page loads', async ({ page, webReady, apiHealth }) => {
    test.skip(!webReady || !apiHealth.ok, 'web or API not ready');
    await navigateTo(page, '/admin/login');
    const userInput = page.locator('input[name="username"], input[name="email"], input[type="email"]').first();
    const passInput = page.locator('input[name="password"], input[type="password"]').first();
    await userInput.fill(ADMIN_USER);
    await passInput.fill(ADMIN_PASS);
    const submit = page.locator('button[type="submit"]').first();
    await submit.click();
    await page.waitForURL((url) => !url.pathname.includes('/login'), { timeout: 15_000 }).catch(() => {});
    await navigateTo(page, '/admin/catalog');
    await waitForApiResponse(page, /\/api\//);
    const body = page.locator('body');
    await expect(body).toBeVisible();
  });

  test('diagnostics page loads and shows status', async ({ page, webReady, apiHealth }) => {
    test.skip(!webReady || !apiHealth.ok, 'web or API not ready');
    await navigateTo(page, '/admin/login');
    const userInput = page.locator('input[name="username"], input[name="email"], input[type="email"]').first();
    const passInput = page.locator('input[name="password"], input[type="password"]').first();
    await userInput.fill(ADMIN_USER);
    await passInput.fill(ADMIN_PASS);
    const submit = page.locator('button[type="submit"]').first();
    await submit.click();
    await page.waitForURL((url) => !url.pathname.includes('/login'), { timeout: 15_000 }).catch(() => {});
    await navigateTo(page, '/admin/diagnostics');
    await waitForApiResponse(page, /\/api\//);
    const body = page.locator('body');
    await expect(body).toBeVisible();
    // Diagnostics should show some status information.
    const statusInfo = page.locator('[data-testid="diagnostics"], .diagnostics, main').first();
    await expect(statusInfo).toBeVisible();
  });

  test('admin site settings page loads', async ({ page, webReady, apiHealth }) => {
    test.skip(!webReady || !apiHealth.ok, 'web or API not ready');
    await navigateTo(page, '/admin/login');
    const userInput = page.locator('input[name="username"], input[name="email"], input[type="email"]').first();
    const passInput = page.locator('input[name="password"], input[type="password"]').first();
    await userInput.fill(ADMIN_USER);
    await passInput.fill(ADMIN_PASS);
    const submit = page.locator('button[type="submit"]').first();
    await submit.click();
    await page.waitForURL((url) => !url.pathname.includes('/login'), { timeout: 15_000 }).catch(() => {});
    await navigateTo(page, '/admin/site');
    await waitForApiResponse(page, /\/api\//);
    const body = page.locator('body');
    await expect(body).toBeVisible();
  });
});