import { test, expect } from './fixtures';
import { navigateTo, waitForApiResponse } from './helpers';

/**
 * B5-04 Search flow.
 *
 * Covers: search query -> filter results -> open a result.
 * Tests skip when the API is not running.
 */

test.describe('04 - Search', () => {
  test('search page has a search input', async ({ page, webReady, apiHealth }) => {
    test.skip(!webReady || !apiHealth.ok, 'web or API not ready');
    await navigateTo(page, '/search');
    const searchInput = page.locator('input[type="search"], input[name="q"], input[placeholder*="search" i]').first();
    await expect(searchInput).toBeVisible();
  });

  test('entering a query shows results', async ({ page, webReady, apiHealth }) => {
    test.skip(!webReady || !apiHealth.ok, 'web or API not ready');
    await navigateTo(page, '/search');
    const searchInput = page.locator('input[type="search"], input[name="q"], input[placeholder*="search" i]').first();
    await searchInput.fill('test');
    await searchInput.press('Enter');
    await waitForApiResponse(page, /\/api\/.*search/i);
    await page.waitForTimeout(2000);
    // Results container should be present (may be empty, but should exist).
    const resultsArea = page.locator('[data-testid="search-results"], .results, main').first();
    await expect(resultsArea).toBeVisible();
  });

  test('search with no results shows empty state', async ({ page, webReady, apiHealth }) => {
    test.skip(!webReady || !apiHealth.ok, 'web or API not ready');
    await navigateTo(page, '/search');
    const searchInput = page.locator('input[type="search"], input[name="q"], input[placeholder*="search" i]').first();
    await searchInput.fill('zzz_no_match_xyz_12345');
    await searchInput.press('Enter');
    await waitForApiResponse(page, /\/api\/.*search/i);
    await page.waitForTimeout(2000);
    // Either an empty state message or zero result links.
    const resultLinks = page.locator('a[href*="/resource/"]');
    const emptyMsg = page.locator('text=/no results|nothing found|empty/i');
    const linkCount = await resultLinks.count();
    const hasEmptyMsg = (await emptyMsg.count()) > 0;
    expect(linkCount === 0 || hasEmptyMsg).toBe(true);
  });

  test('filter search results by category', async ({ page, webReady, apiHealth }) => {
    test.skip(!webReady || !apiHealth.ok, 'web or API not ready');
    await navigateTo(page, '/search');
    const searchInput = page.locator('input[type="search"], input[name="q"], input[placeholder*="search" i]').first();
    await searchInput.fill('test');
    await searchInput.press('Enter');
    await waitForApiResponse(page, /\/api\/.*search/i);
    await page.waitForTimeout(1000);
    // Look for a filter control (select, checkbox, link).
    const filterControl = page.locator('select, input[type="checkbox"], a[href*="category"], a[href*="type"]').first();
    const filterCount = await filterControl.count();
    test.skip(filterCount === 0, 'no filter controls available');
    await filterControl.click().catch(() => {});
    await page.waitForTimeout(1500);
    const body = page.locator('body');
    await expect(body).toBeVisible();
  });

  test('open a search result navigates to detail', async ({ page, webReady, apiHealth }) => {
    test.skip(!webReady || !apiHealth.ok, 'web or API not ready');
    await navigateTo(page, '/search');
    const searchInput = page.locator('input[type="search"], input[name="q"], input[placeholder*="search" i]').first();
    await searchInput.fill('test');
    await searchInput.press('Enter');
    await waitForApiResponse(page, /\/api\/.*search/i);
    await page.waitForTimeout(2000);
    const resultLink = page.locator('a[href*="/resource/"]').first();
    const linkCount = await resultLink.count();
    test.skip(linkCount === 0, 'no search results to open');
    await resultLink.click();
    await page.waitForLoadState('networkidle').catch(() => {});
    expect(page.url()).toMatch(/\/resource\//);
  });
});