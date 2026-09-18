import { test as base, expect, type Page, type APIRequestContext } from '@playwright/test';
import { waitForApiReady, waitForWebReady, loginViaApi, loginViaUi, WEB_BASE_URL, type ApiHealth } from './helpers';

/**
 * Shared E2E fixtures for CloudSite.
 *
 * - `apiHealth`: probes the API once per worker; tests skip when unavailable.
 * - `webReady`: probes the web app once; tests skip when unavailable.
 * - `apiAuth`: an APIRequestContext already authenticated as a test user.
 * - `freshPage`: a clean page with localStorage cleared.
 */

export type E2EFixtures = {
  apiHealth: ApiHealth;
  webReady: boolean;
  apiAuth: APIRequestContext;
  freshPage: Page;
  loggedInPage: Page;
};

export const test = base.extend<E2EFixtures>({
  apiHealth: async ({}, use) => {
    const health = await waitForApiReady();
    test.skip(!health.ok, `API not reachable: ${health.reason ?? 'unknown'}`);
    await use(health);
  },

  webReady: async ({}, use) => {
    const ok = await waitForWebReady();
    test.skip(!ok, 'Web app not reachable on localhost:3000');
    await use(ok);
  },

  apiAuth: async ({ apiHealth }, use) => {
    const ctx = await loginViaApi(apiHealth);
    test.skip(ctx === null, 'Unable to authenticate via API for fixture');
    await use(ctx as APIRequestContext);
  },

  freshPage: async ({ browser }, use) => {
    const context = await browser.newContext({ baseURL: WEB_BASE_URL });
    const page = await context.newPage();
    await page.goto('/').catch(() => {});
    await page.evaluate(() => {
      try {
        window.localStorage.clear();
        window.sessionStorage.clear();
      } catch {
        // ignore
      }
    });
    await use(page);
    await context.close();
  },

  loggedInPage: async ({ page, webReady, apiHealth }, use) => {
    test.skip(!webReady || !apiHealth.ok, 'web or API not ready');
    await loginViaUi(page, {
      username: process.env.E2E_USER ?? 'nathan',
      password: process.env.E2E_PASS ?? '647lsxasd',
    });
    await use(page);
  },
});

export { expect };
export { test as e2eTest };