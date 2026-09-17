import { test, expect } from './fixtures';
import { navigateTo, waitForApiResponse, uniqueName } from './helpers';

/**
 * B5-03 Browse flow.
 *
 * Covers: homepage -> category/resource list -> resource detail.
 * Tests skip when the API is not running.
 */

test.describe('03 - Browse', () => {
  test('homepage shows resource listings or categories', async ({ page, webReady, apiHealth }) => {
    test.skip(!webReady || !apiHealth.ok, 'web or API not ready');
    await navigateTo(page, '/');
    // Look for links to resources, categories, or browse.
    const resourceLinks = page.locator('a[href*="/resource/"], a[href*="/resources/"], a[href*="/browse"]');
    const count = await resourceLinks.count();
    expect(count).toBeGreaterThan(0);
  });

  test('browse page lists resources', async ({ page, webReady, apiHealth }) => {
    test.skip(!webReady || !apiHealth.ok, 'web or API not ready');
    await navigateTo(page, '/browse');
    await waitForApiResponse(page, /\/api\//);
    // The browse page should have some content items.
    const items = page.locator('a[href*="/resource/"], [data-testid="resource-item"], article, .resource-card');
    const count = await items.count();
    expect(count).toBeGreaterThan(0);
  });

  test('navigate from browse to resource detail', async ({ page, webReady, apiHealth }) => {
    test.skip(!webReady || !apiHealth.ok, 'web or API not ready');
    await navigateTo(page, '/browse');
    await waitForApiResponse(page, /\/api\//);
    const resourceLink = page.locator('a[href*="/resource/"]').first();
    const linkCount = await resourceLink.count();
    test.skip(linkCount === 0, 'no resources available to browse');
    await resourceLink.click();
    await page.waitForLoadState('networkidle').catch(() => {});
    // Should now be on a resource detail page.
    expect(page.url()).toMatch(/\/resource\//);
    const body = page.locator('body');
    await expect(body).toBeVisible();
  });

  test('resource detail page shows content', async ({ page, webReady, apiHealth }) => {
    test.skip(!webReady || !apiHealth.ok, 'web or API not ready');
    await navigateTo(page, '/browse');
    await waitForApiResponse(page, /\/api\//);
    const resourceLink = page.locator('a[href*="/resource/"]').first();
    const linkCount = await resourceLink.count();
    test.skip(linkCount === 0, 'no resources available');
    await resourceLink.click();
    await page.waitForLoadState('networkidle').catch(() => {});
    // Detail page should have a title or heading.
    const heading = page.locator('h1, h2, [data-testid="resource-title"]').first();
    await expect(heading).toBeVisible();
  });

  test('resources type filter page loads', async ({ page, webReady, apiHealth }) => {
    test.skip(!webReady || !apiHealth.ok, 'web or API not ready');
    await navigateTo(page, '/resources');
    const body = page.locator('body');
    await expect(body).toBeVisible();
  });
});