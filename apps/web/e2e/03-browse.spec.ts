import { test, expect } from './fixtures';
import { navigateTo } from './helpers';

/**
 * Deterministic browse flow.
 *
 * Environment availability may skip through shared fixtures. Once the guarded
 * E2E seed is enabled, missing seeded content is a real failure.
 */

test.describe('03 - Browse', () => {
  test('homepage exposes the browse entry', async ({ loggedInPage }) => {
    await navigateTo(loggedInPage, '/');
    await expect(loggedInPage.locator('a[href="/browse"]').first()).toBeVisible();
  });

  test('browse lists the deterministic seeded resource', async ({
    loggedInPage,
    e2eSeed,
  }) => {
    await navigateTo(loggedInPage, '/browse?sort=name');

    const resourceLink = loggedInPage.locator(
      `a.resource-copy[href="/resource/${e2eSeed.resource_id}"]`,
    );
    await expect(resourceLink).toBeVisible();
    await expect(resourceLink).toContainText(e2eSeed.resource_name);
  });

  test('seeded browse resource opens its exact detail page', async ({
    loggedInPage,
    e2eSeed,
  }) => {
    await navigateTo(loggedInPage, '/browse?sort=name');

    const resourceLink = loggedInPage.locator(
      `a.resource-copy[href="/resource/${e2eSeed.resource_id}"]`,
    );
    await expect(resourceLink).toBeVisible();
    await resourceLink.click();

    await expect(loggedInPage).toHaveURL(
      new RegExp(`/resource/${e2eSeed.resource_id}$`),
    );
    await expect(loggedInPage.getByRole('heading', {
      level: 1,
      name: e2eSeed.resource_name,
    })).toBeVisible();
  });
});
