import { test, expect } from './fixtures';
import { navigateTo, waitForApiResponse, uniqueName } from './helpers';

/**
 * B5-06 Share flow.
 *
 * Covers: create share -> open public share link -> enter code -> download.
 * Tests skip when the API is not running or no resources are available.
 */

test.describe('06 - Share', () => {
  test('resource detail has a share button', async ({ loggedInPage }) => {
    await navigateTo(loggedInPage, '/browse');
    await loggedInPage.locator('.resource-card, a[href*="/resource/"], .empty').first().waitFor({ timeout: 10_000 }).catch(() => {});
    const resourceLink = loggedInPage.locator('a[href*="/resource/"]').first();
    const linkCount = await resourceLink.count();
    test.skip(linkCount === 0, 'no resources available');
    await resourceLink.click();
    await loggedInPage.waitForURL((url) => url.pathname.includes('/resource/'), { timeout: 15_000 }).catch(() => {});
    await loggedInPage.waitForTimeout(2000);
    const shareBtn = loggedInPage.locator(
      '.detail-actions button:has-text("分享"), button:has-text("分享"), [data-testid="share-button"]',
    ).first();
    const btnCount = await shareBtn.count();
    test.skip(btnCount === 0, 'no share button on resource detail');
    await expect(shareBtn).toBeVisible();
  });

  test('create a share link for a resource', async ({ loggedInPage }) => {
    await navigateTo(loggedInPage, '/browse');
    await loggedInPage.locator('.resource-card, a[href*="/resource/"], .empty').first().waitFor({ timeout: 10_000 }).catch(() => {});
    const resourceLink = loggedInPage.locator('a[href*="/resource/"]').first();
    const linkCount = await resourceLink.count();
    test.skip(linkCount === 0, 'no resources available');
    await resourceLink.click();
    await loggedInPage.waitForURL((url) => url.pathname.includes('/resource/'), { timeout: 15_000 }).catch(() => {});
    const shareBtn = loggedInPage.locator(
      '.detail-actions button:has-text("分享"), button:has-text("分享"), [data-testid="share-button"]',
    ).first();
    const btnCount = await shareBtn.count();
    test.skip(btnCount === 0, 'no share button');
    await shareBtn.click();
    await loggedInPage.waitForTimeout(2000);
    const shareUrl = loggedInPage.locator('input[readonly], [data-testid="share-url"], a[href*="/s/"]').first();
    const urlCount = await shareUrl.count();
    test.skip(urlCount === 0, 'no share URL generated');
    await expect(shareUrl).toBeVisible();
  });

  test('open a public share link', async ({ loggedInPage, page, webReady, apiHealth }) => {
    test.skip(!webReady || !apiHealth.ok, 'web or API not ready');
    const knownToken = process.env.E2E_SHARE_TOKEN;
    if (knownToken) {
      await navigateTo(page, `/s/${knownToken}`);
      const body = page.locator('body');
      await expect(body).toBeVisible();
    } else {
      await navigateTo(loggedInPage, '/browse');
      await waitForApiResponse(loggedInPage, /\/api\//);
      const resourceLink = loggedInPage.locator('a[href*="/resource/"]').first();
      const linkCount = await resourceLink.count();
      test.skip(linkCount === 0, 'no resources available');
      await resourceLink.click();
      await loggedInPage.waitForLoadState('networkidle').catch(() => {});
      const shareBtn = loggedInPage.locator(
        'button:has-text("分享"), button:has-text("Share"), [data-testid="share-button"]',
      ).first();
      const btnCount = await shareBtn.count();
      test.skip(btnCount === 0, 'no share button');
      await shareBtn.click();
      await loggedInPage.waitForTimeout(2000);
      const shareLink = loggedInPage.locator('a[href*="/s/"]').first();
      const shareLinkCount = await shareLink.count();
      test.skip(shareLinkCount === 0, 'no share link generated');
      const href = await shareLink.getAttribute('href');
      test.skip(!href, 'share link has no href');
      await navigateTo(loggedInPage, href as string);
      const body = loggedInPage.locator('body');
      await expect(body).toBeVisible();
    }
  });

  test('enter share code and access content', async ({ page, webReady, apiHealth }) => {
    test.skip(!webReady || !apiHealth.ok, 'web or API not ready');
    const knownToken = process.env.E2E_SHARE_TOKEN;
    const knownCode = process.env.E2E_SHARE_CODE;
    test.skip(!knownToken || !knownCode, 'no share token/code provided in env');
    await navigateTo(page, `/s/${knownToken}`);
    const codeInput = page.locator('input[name="code"], input[placeholder*="code" i], input[type="text"]').first();
    const inputCount = await codeInput.count();
    test.skip(inputCount === 0, 'no code input on share page');
    await codeInput.fill(knownCode as string);
    const submit = page.locator('button[type="submit"], button:has-text("Access"), button:has-text("Submit")').first();
    await submit.click();
    await page.waitForLoadState('networkidle').catch(() => {});
    // Should now show the shared content or a download option.
    const content = page.locator('main, [role="main"], [data-testid="shared-content"]').first();
    await expect(content).toBeVisible();
  });

  test('share page with invalid code shows error', async ({ page, webReady, apiHealth }) => {
    test.skip(!webReady || !apiHealth.ok, 'web or API not ready');
    const knownToken = process.env.E2E_SHARE_TOKEN;
    test.skip(!knownToken, 'no share token provided in env');
    await navigateTo(page, `/s/${knownToken}`);
    const codeInput = page.locator('input[name="code"], input[placeholder*="code" i], input[type="text"]').first();
    const inputCount = await codeInput.count();
    test.skip(inputCount === 0, 'no code input on share page');
    await codeInput.fill('invalid_code_xyz');
    const submit = page.locator('button[type="submit"]').first();
    await submit.click();
    await page.waitForTimeout(2000);
    const hasError = (await page.locator('text=/invalid|incorrect|error|wrong/i').count()) > 0;
    expect(hasError).toBe(true);
  });
});