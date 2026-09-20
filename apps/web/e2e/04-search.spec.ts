import { test, expect } from './fixtures';
import { navigateTo } from './helpers';

/**
 * Deterministic search flow backed by the guarded E2E content seed.
 */

test.describe('04 - Search', () => {
  test('search page exposes the query input', async ({ loggedInPage }) => {
    await navigateTo(loggedInPage, '/search');
    await expect(
      loggedInPage.getByPlaceholder('搜索软件、图库、视频、教程和文件'),
    ).toBeVisible();
  });

  test('seeded query finds the exact resource and opens detail', async ({
    loggedInPage,
    e2eSeed,
  }) => {
    await navigateTo(loggedInPage, '/search');

    const searchInput = loggedInPage.getByPlaceholder(
      '搜索软件、图库、视频、教程和文件',
    );
    await searchInput.fill(e2eSeed.search_query);
    await searchInput.press('Enter');

    const resultLink = loggedInPage.locator(
      `a.search-result-card[href="/resource/${e2eSeed.resource_id}"]`,
    );
    await expect(resultLink).toBeVisible();
    await expect(resultLink).toContainText(e2eSeed.resource_name);

    await resultLink.click();
    await expect(loggedInPage).toHaveURL(
      new RegExp(`/resource/${e2eSeed.resource_id}$`),
    );
    await expect(loggedInPage.getByRole('heading', {
      level: 1,
      name: e2eSeed.resource_name,
    })).toBeVisible();
  });

  test('no-match query renders the real empty state', async ({
    loggedInPage,
    e2eSeed,
  }) => {
    void e2eSeed;
    await navigateTo(loggedInPage, '/search');

    const query = 'zzz_cloudsite_e2e_no_match_987654321';
    const searchInput = loggedInPage.getByPlaceholder(
      '搜索软件、图库、视频、教程和文件',
    );
    await searchInput.fill(query);
    await searchInput.press('Enter');

    await expect(
      loggedInPage.locator('.empty.search-state').filter({
        hasText: `没有找到“${query}”`,
      }),
    ).toBeVisible();
  });
});
