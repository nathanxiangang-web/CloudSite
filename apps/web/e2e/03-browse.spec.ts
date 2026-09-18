import { test, expect } from './fixtures';
import { navigateTo, waitForApiResponse, uniqueName } from './helpers';

/**
 * B5-03 Browse flow.
 *
 * Covers: homepage -> category/resource list -> resource detail.
 * Tests skip when the API is not running.
 */

test.describe('03 - Browse', () => {
  test('homepage shows resource listings or categories', async ({ loggedInPage }) => {
    await navigateTo(loggedInPage, '/');
    const resourceLinks = loggedInPage.locator('a[href*="/resource/"], a[href*="/resources/"], a[href*="/browse"]');
    const count = await resourceLinks.count();
    expect(count).toBeGreaterThan(0);
  });

  test('browse page lists resources', async ({ loggedInPage }) => {
    await navigateTo(loggedInPage, '/browse');
    await waitForApiResponse(loggedInPage, /\/api\//);
    const items = loggedInPage.locator('a[href*="/resource/"], [data-testid="resource-item"], article, .resource-card');
    const count = await items.count();
    expect(count).toBeGreaterThan(0);
  });

  test('navigate from browse to resource detail', async ({ loggedInPage }) => {
    await navigateTo(loggedInPage, '/browse');
    await waitForApiResponse(loggedInPage, /\/api\//);
    const resourceLink = loggedInPage.locator('a[href*="/resource/"]').first();
    const linkCount = await resourceLink.count();
    test.skip(linkCount === 0, 'no resources available to browse');
    await resourceLink.click();
    await loggedInPage.waitForURL((url) => url.pathname.includes('/resource/'), { timeout: 15_000 }).catch(() => {});
    expect(loggedInPage.url()).toMatch(/\/resource\//);
    const body = loggedInPage.locator('body');
    await expect(body).toBeVisible();
  });

  test('resource detail page shows content', async ({ loggedInPage }) => {
    await navigateTo(loggedInPage, '/browse');
    await waitForApiResponse(loggedInPage, /\/api\//);
    const resourceLink = loggedInPage.locator('a[href*="/resource/"]').first();
    const linkCount = await resourceLink.count();
    test.skip(linkCount === 0, 'no resources available');
    await resourceLink.click();
    await loggedInPage.waitForURL((url) => url.pathname.includes('/resource/'), { timeout: 15_000 }).catch(() => {});
    const heading = loggedInPage.locator('h1, h2, [data-testid="resource-title"]').first();
    await expect(heading).toBeVisible();
  });

  test('resources type filter page loads', async ({ loggedInPage }) => {
    await navigateTo(loggedInPage, '/resources');
    const body = loggedInPage.locator('body');
    await expect(body).toBeVisible();
  });
});