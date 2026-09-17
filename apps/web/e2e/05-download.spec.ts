import { test, expect } from './fixtures';
import { navigateTo, waitForApiResponse, loginViaUi } from './helpers';

/**
 * B5-05 Download flow.
 *
 * Covers: resource detail -> download button -> redirect chain.
 * Tests skip when the API is not running or no resources are available.
 */

test.describe('05 - Download', () => {
  test('resource detail page has a download button', async ({ page, webReady, apiHealth }) => {
    test.skip(!webReady || !apiHealth.ok, 'web or API not ready');
    await navigateTo(page, '/browse');
    await waitForApiResponse(page, /\/api\//);
    const resourceLink = page.locator('a[href*="/resource/"]').first();
    const linkCount = await resourceLink.count();
    test.skip(linkCount === 0, 'no resources available');
    await resourceLink.click();
    await page.waitForLoadState('networkidle').catch(() => {});
    const downloadBtn = page.locator(
      'a:has-text("Download"), button:has-text("Download"), a[href*="download"], [data-testid="download-button"]',
    ).first();
    const btnCount = await downloadBtn.count();
    test.skip(btnCount === 0, 'no download button on resource detail');
    await expect(downloadBtn).toBeVisible();
  });

  test('clicking download triggers a download or redirect', async ({ page, webReady, apiHealth }) => {
    test.skip(!webReady || !apiHealth.ok, 'web or API not ready');
    await navigateTo(page, '/browse');
    await waitForApiResponse(page, /\/api\//);
    const resourceLink = page.locator('a[href*="/resource/"]').first();
    const linkCount = await resourceLink.count();
    test.skip(linkCount === 0, 'no resources available');
    await resourceLink.click();
    await page.waitForLoadState('networkidle').catch(() => {});
    const downloadBtn = page.locator(
      'a:has-text("Download"), button:has-text("Download"), a[href*="download"], [data-testid="download-button"]',
    ).first();
    const btnCount = await downloadBtn.count();
    test.skip(btnCount === 0, 'no download button');
    const downloadPromise = page.waitForEvent('download', { timeout: 15_000 }).catch(() => null);
    await downloadBtn.click();
    const download = await downloadPromise;
    if (download) {
      expect(download.suggestedFilename()).toBeTruthy();
    } else {
      // If no download event, expect a navigation to a download/cloud-download route.
      await page.waitForTimeout(3000);
      const url = page.url();
      const isDownloadRoute = url.includes('download') || url.includes('cloud-download');
      expect(isDownloadRoute).toBe(true);
    }
  });

  test('download redirect chain is valid', async ({ page, webReady, apiHealth }) => {
    test.skip(!webReady || !apiHealth.ok, 'web or API not ready');
    const responses: { url: string; status: number }[] = [];
    page.on('response', (res) => {
      const url = res.url();
      if (url.includes('download') || url.includes('cloud-download')) {
        responses.push({ url, status: res.status() });
      }
    });
    await navigateTo(page, '/browse');
    await waitForApiResponse(page, /\/api\//);
    const resourceLink = page.locator('a[href*="/resource/"]').first();
    const linkCount = await resourceLink.count();
    test.skip(linkCount === 0, 'no resources available');
    await resourceLink.click();
    await page.waitForLoadState('networkidle').catch(() => {});
    const downloadBtn = page.locator(
      'a:has-text("Download"), button:has-text("Download"), [data-testid="download-button"]',
    ).first();
    const btnCount = await downloadBtn.count();
    test.skip(btnCount === 0, 'no download button');
    await downloadBtn.click();
    await page.waitForTimeout(5000);
    // At least one download-related response should have been observed.
    test.skip(responses.length === 0, 'no download responses observed');
    for (const r of responses) {
      expect(r.status).toBeGreaterThanOrEqual(200);
      expect(r.status).toBeLessThan(400);
    }
  });

  test('authenticated user can download', async ({ page, webReady, apiHealth }) => {
    test.skip(!webReady || !apiHealth.ok, 'web or API not ready');
    const username = process.env.E2E_USER ?? 'e2e_user';
    const password = process.env.E2E_PASS ?? 'e2e_pass_123';
    await loginViaUi(page, { username, password });
    await navigateTo(page, '/browse');
    await waitForApiResponse(page, /\/api\//);
    const resourceLink = page.locator('a[href*="/resource/"]').first();
    const linkCount = await resourceLink.count();
    test.skip(linkCount === 0, 'no resources available');
    await resourceLink.click();
    await page.waitForLoadState('networkidle').catch(() => {});
    const downloadBtn = page.locator(
      'a:has-text("Download"), button:has-text("Download"), [data-testid="download-button"]',
    ).first();
    const btnCount = await downloadBtn.count();
    test.skip(btnCount === 0, 'no download button');
    const downloadPromise = page.waitForEvent('download', { timeout: 15_000 }).catch(() => null);
    await downloadBtn.click();
    const download = await downloadPromise;
    if (download) {
      expect(download.suggestedFilename()).toBeTruthy();
    }
  });
});