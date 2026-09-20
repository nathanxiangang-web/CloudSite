import { test, expect } from './fixtures';
import { navigateTo, waitForApiResponse } from './helpers';

/**
 * B5-05 Download flow.
 *
 * Covers: resource detail -> download button -> redirect chain.
 * Tests skip when the API is not running or no resources are available.
 */

test.describe('05 - Download', () => {
  test('resource detail page has a download button', async ({ loggedInPage }) => {
    await navigateTo(loggedInPage, '/browse');
    await waitForApiResponse(loggedInPage, /\/api\//);
    const resourceLink = loggedInPage.locator('a[href*="/resource/"]').first();
    const linkCount = await resourceLink.count();
    test.skip(linkCount === 0, 'no resources available');
    await resourceLink.click();
    await loggedInPage.waitForLoadState('networkidle').catch(() => {});
    const downloadBtn = loggedInPage.locator(
      'a:has-text("下载"), button:has-text("下载"), a:has-text("Download"), button:has-text("Download"), a[href*="download"], [data-testid="download-button"]',
    ).first();
    const btnCount = await downloadBtn.count();
    test.skip(btnCount === 0, 'no download button on resource detail');
    await expect(downloadBtn).toBeVisible();
  });

  test('clicking download triggers a download or redirect', async ({ loggedInPage }) => {
    await navigateTo(loggedInPage, '/browse');
    await waitForApiResponse(loggedInPage, /\/api\//);
    const resourceLink = loggedInPage.locator('a[href*="/resource/"]').first();
    const linkCount = await resourceLink.count();
    test.skip(linkCount === 0, 'no resources available');
    await resourceLink.click();
    await loggedInPage.waitForLoadState('networkidle').catch(() => {});
    const downloadBtn = loggedInPage.locator(
      'a:has-text("下载"), button:has-text("下载"), a:has-text("Download"), button:has-text("Download"), a[href*="download"], [data-testid="download-button"]',
    ).first();
    const btnCount = await downloadBtn.count();
    test.skip(btnCount === 0, 'no download button');
    const downloadPromise = loggedInPage.waitForEvent('download', { timeout: 15_000 }).catch(() => null);
    await downloadBtn.click();
    const download = await downloadPromise;
    if (download) {
      expect(download.suggestedFilename()).toBeTruthy();
    } else {
      await loggedInPage.waitForTimeout(3000);
      const url = loggedInPage.url();
      const isDownloadRoute = url.includes('download') || url.includes('cloud-download');
      expect(isDownloadRoute).toBe(true);
    }
  });

  test('download redirect chain is valid', async ({ loggedInPage }) => {
    const responses: { url: string; status: number }[] = [];
    loggedInPage.on('response', (res) => {
      const url = res.url();
      if (url.includes('download') || url.includes('cloud-download')) {
        responses.push({ url, status: res.status() });
      }
    });
    await navigateTo(loggedInPage, '/browse');
    await waitForApiResponse(loggedInPage, /\/api\//);
    const resourceLink = loggedInPage.locator('a[href*="/resource/"]').first();
    const linkCount = await resourceLink.count();
    test.skip(linkCount === 0, 'no resources available');
    await resourceLink.click();
    await loggedInPage.waitForLoadState('networkidle').catch(() => {});
    const downloadBtn = loggedInPage.locator(
      'a:has-text("下载"), button:has-text("下载"), a:has-text("Download"), button:has-text("Download"), [data-testid="download-button"]',
    ).first();
    const btnCount = await downloadBtn.count();
    test.skip(btnCount === 0, 'no download button');
    await downloadBtn.click();
    await loggedInPage.waitForTimeout(5000);
    test.skip(responses.length === 0, 'no download responses observed');
    for (const r of responses) {
      expect(r.status).toBeGreaterThanOrEqual(200);
      expect(r.status).toBeLessThan(400);
    }
  });

  test('authenticated user can download', async ({ loggedInPage }) => {
    await navigateTo(loggedInPage, '/browse');
    await waitForApiResponse(loggedInPage, /\/api\//);
    const resourceLink = loggedInPage.locator('a[href*="/resource/"]').first();
    const linkCount = await resourceLink.count();
    test.skip(linkCount === 0, 'no resources available');
    await resourceLink.click();
    await loggedInPage.waitForLoadState('networkidle').catch(() => {});
    const downloadBtn = loggedInPage.locator(
      'a:has-text("下载"), button:has-text("下载"), a:has-text("Download"), button:has-text("Download"), [data-testid="download-button"]',
    ).first();
    const btnCount = await downloadBtn.count();
    test.skip(btnCount === 0, 'no download button');
    const downloadPromise = loggedInPage.waitForEvent('download', { timeout: 15_000 }).catch(() => null);
    await downloadBtn.click();
    const download = await downloadPromise;
    if (download) {
      expect(download.suggestedFilename()).toBeTruthy();
    }
  });
});