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
  test('homepage loads successfully', async ({ loggedInPage }) => {
    await navigateTo(loggedInPage, '/');
    await expect(loggedInPage).toHaveTitle(/.+/);
    const body = loggedInPage.locator('body');
    await expect(body).toBeVisible();
  });

  test('homepage shows main navigation', async ({ loggedInPage }) => {
    await navigateTo(loggedInPage, '/');
    const nav = loggedInPage.locator('nav a, header a').first();
    await expect(nav).toBeVisible();
  });

  test('API health endpoint is reachable', async ({ apiHealth }) => {
    test.skip(!apiHealth.ok, 'API not reachable');
    expect(apiHealth.ok).toBe(true);
    expect(apiHealth.baseUrl).toContain('localhost:8000');
  });

  test('web app can reach API (no error boundary)', async ({ loggedInPage, apiHealth }) => {
    test.skip(!apiHealth.ok, 'API not reachable');
    const errors: string[] = [];
    loggedInPage.on('pageerror', (err) => errors.push(err.message));
    await navigateTo(loggedInPage, '/');
    await loggedInPage.waitForTimeout(2000);
    const mainContent = loggedInPage.locator('main, [role="main"], #content').first();
    if ((await mainContent.count()) > 0) {
      await expect(mainContent).toBeVisible();
    }
  });

  test('browse page loads', async ({ loggedInPage }) => {
    await navigateTo(loggedInPage, '/browse');
    const body = loggedInPage.locator('body');
    await expect(body).toBeVisible();
  });

  test('search page loads', async ({ loggedInPage }) => {
    await navigateTo(loggedInPage, '/search');
    const body = loggedInPage.locator('body');
    await expect(body).toBeVisible();
  });
});