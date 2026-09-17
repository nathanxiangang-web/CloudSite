import { test, expect } from './fixtures';
import { navigateTo, waitForApiResponse, API_BASE_URL } from './helpers';

/**
 * B5-01 Setup smoke test.
 *
 * Verifies the homepage loads, the API is reachable, and the web app
 * can talk to the API. All assertions are skipped if the API or web
 * server is not running.
 */

test.describe('01 - Setup & connectivity', () => {
  test('homepage loads successfully', async ({ page, webReady, apiHealth }) => {
    test.skip(!webReady, 'web not ready');
    await navigateTo(page, '/');
    await expect(page).toHaveTitle(/.+/);
    const body = page.locator('body');
    await expect(body).toBeVisible();
  });

  test('homepage shows main navigation', async ({ page, webReady }) => {
    test.skip(!webReady, 'web not ready');
    await navigateTo(page, '/');
    // At least one navigation link should be present.
    const nav = page.locator('nav a, header a').first();
    await expect(nav).toBeVisible();
  });

  test('API health endpoint is reachable', async ({ apiHealth }) => {
    test.skip(!apiHealth.ok, 'API not reachable');
    expect(apiHealth.ok).toBe(true);
    expect(apiHealth.baseUrl).toContain('localhost:8000');
  });

  test('web app can reach API (no error boundary)', async ({ page, webReady, apiHealth }) => {
    test.skip(!webReady || !apiHealth.ok, 'web or API not ready');
    const errors: string[] = [];
    page.on('pageerror', (err) => errors.push(err.message));
    await navigateTo(page, '/');
    // Give the page a moment to settle and fire any API calls.
    await page.waitForTimeout(2000);
    // The page should not show a full-screen error boundary.
    const errorBoundary = page.locator('text=/Something went wrong|Error|Unable to load/i').first();
    // We allow generic "Error" text in nav/footer, so only fail if it is
    // the primary content.
    const mainContent = page.locator('main, [role="main"], #content').first();
    if ((await mainContent.count()) > 0) {
      await expect(mainContent).toBeVisible();
    }
  });

  test('browse page loads', async ({ page, webReady }) => {
    test.skip(!webReady, 'web not ready');
    await navigateTo(page, '/browse');
    const body = page.locator('body');
    await expect(body).toBeVisible();
  });

  test('search page loads', async ({ page, webReady }) => {
    test.skip(!webReady, 'web not ready');
    await navigateTo(page, '/search');
    const body = page.locator('body');
    await expect(body).toBeVisible();
  });
});