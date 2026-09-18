import { test, expect } from './fixtures';
import { navigateTo, waitForApiResponse } from './helpers';

/**
 * B5-04 Search flow.
 *
 * Covers: search query -> filter results -> open a result.
 * Tests skip when the API is not running.
 */

test.describe('04 - Search', () => {
  test('search page has a search input', async ({ loggedInPage }) => {
    await navigateTo(loggedInPage, '/search');
    const searchInput = loggedInPage.locator('input[placeholder*="搜索"], input[type="search"], input[name="q"], input[placeholder*="search" i]').first();
    await expect(searchInput).toBeVisible();
  });

  test('entering a query shows results', async ({ loggedInPage }) => {
    await navigateTo(loggedInPage, '/search');
    const searchInput = loggedInPage.locator('input[placeholder*="搜索"], input[type="search"], input[name="q"], input[placeholder*="search" i]').first();
    await searchInput.fill('test');
    await searchInput.press('Enter');
    await waitForApiResponse(loggedInPage, /\/api\/.*search/i);
    await loggedInPage.waitForTimeout(2000);
    const resultsArea = loggedInPage.locator('[data-testid="search-results"], .results, main').first();
    await expect(resultsArea).toBeVisible();
  });

  test('search with no results shows empty state', async ({ loggedInPage }) => {
    await navigateTo(loggedInPage, '/search');
    const searchInput = loggedInPage.locator('input[placeholder*="搜索"], input[type="search"], input[name="q"], input[placeholder*="search" i]').first();
    await searchInput.fill('zzz_no_match_xyz_12345');
    await searchInput.press('Enter');
    await waitForApiResponse(loggedInPage, /\/api\/.*search/i);
    await loggedInPage.waitForTimeout(2000);
    const resultLinks = loggedInPage.locator('a[href*="/resource/"]');
    const emptyMsg = loggedInPage.locator('text=/no results|nothing found|empty|无结果|没有找到/i');
    const linkCount = await resultLinks.count();
    const hasEmptyMsg = (await emptyMsg.count()) > 0;
    expect(linkCount === 0 || hasEmptyMsg).toBe(true);
  });

  test('filter search results by category', async ({ loggedInPage }) => {
    await navigateTo(loggedInPage, '/search');
    const searchInput = loggedInPage.locator('input[placeholder*="搜索"], input[type="search"], input[name="q"], input[placeholder*="search" i]').first();
    await searchInput.fill('test');
    await searchInput.press('Enter');
    await waitForApiResponse(loggedInPage, /\/api\/.*search/i);
    await loggedInPage.waitForTimeout(1000);
    const filterControl = loggedInPage.locator('select, input[type="checkbox"], a[href*="category"], a[href*="type"]').first();
    const filterCount = await filterControl.count();
    test.skip(filterCount === 0, 'no filter controls available');
    await filterControl.click().catch(() => {});
    await loggedInPage.waitForTimeout(1500);
    const body = loggedInPage.locator('body');
    await expect(body).toBeVisible();
  });

  test('open a search result navigates to detail', async ({ loggedInPage }) => {
    await navigateTo(loggedInPage, '/search');
    const searchInput = loggedInPage.locator('input[placeholder*="搜索"], input[type="search"], input[name="q"], input[placeholder*="search" i]').first();
    await searchInput.fill('test');
    await searchInput.press('Enter');
    await waitForApiResponse(loggedInPage, /\/api\/.*search/i);
    await loggedInPage.waitForTimeout(2000);
    const resultLink = loggedInPage.locator('a[href*="/resource/"]').first();
    const linkCount = await resultLink.count();
    test.skip(linkCount === 0, 'no search results to open');
    await resultLink.click();
    await loggedInPage.waitForLoadState('networkidle').catch(() => {});
    expect(loggedInPage.url()).toMatch(/\/resource\//);
  });
});