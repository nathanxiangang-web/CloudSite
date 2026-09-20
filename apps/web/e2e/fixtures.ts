import { test as base, expect, type Page, type APIRequestContext } from '@playwright/test';
import { waitForApiReady, waitForWebReady, loginViaApi, loginViaUi, WEB_BASE_URL, type ApiHealth } from './helpers';

/**
 * Shared E2E fixtures for CloudSite.
 *
 * - `apiHealth`: probes the API once per worker; tests skip when unavailable.
 * - `webReady`: probes the web app once; tests skip when unavailable.
 * - `apiAuth`: an APIRequestContext already authenticated as a test user.
 * - `e2eSeed`: deterministic content/search data from the guarded dev-only seed route.
 * - `freshPage`: a clean page with localStorage cleared.
 */

export type E2ESeedData = {
  root_mapping_id: number;
  resource_id: string;
  resource_name: string;
  search_query: string;
  search_indexed: number;
  download_provider_seeded: false;
};

export type E2EFixtures = {
  apiHealth: ApiHealth;
  webReady: boolean;
  apiAuth: APIRequestContext;
  e2eSeed: E2ESeedData;
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
    if (ctx === null) {
      test.skip(true, 'Unable to authenticate via API for fixture');
      return;
    }
    try {
      await use(ctx);
    } finally {
      await ctx.dispose();
    }
  },

  e2eSeed: async ({ apiAuth }, use) => {
    const response = await apiAuth.post('/api/_e2e/seed', {
      headers: { 'X-E2E-Run': '1' },
    });
    if (response.status() === 404) {
      test.skip(
        true,
        'Deterministic E2E seed is disabled; set CLOUDSITE_E2E_SEED_ENABLED=true in the dev E2E environment',
      );
      return;
    }
    if (!response.ok()) {
      throw new Error(
        `E2E seed failed with HTTP ${response.status()}: ${await response.text()}`,
      );
    }
    const seed = await response.json() as E2ESeedData;
    if (!seed.resource_id || !seed.resource_name || !seed.search_query) {
      throw new Error('E2E seed returned an invalid payload');
    }
    await use(seed);
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

  loggedInPage: async ({ page, webReady, apiHealth, apiAuth }, use) => {
    test.skip(!webReady || !apiHealth.ok, 'web or API not ready');
    // Resolving apiAuth first guarantees the shared E2E_USER/E2E_PASS account
    // exists (or cleanly skips when the environment cannot provision it).
    void apiAuth;
    await loginViaUi(page);
    await use(page);
  },
});

export { expect };
export { test as e2eTest };