import { test, expect } from './fixtures';
import { navigateTo, loginViaUi, registerViaUi, logoutViaUi, isAuthenticated, uniqueName } from './helpers';

/**
 * B5-02 Authentication flow.
 *
 * Covers: register -> login -> authenticated state -> logout.
 * Tests skip when the API is not running (auth requires backend).
 */

test.describe('02 - Authentication', () => {
  test('register a new user', async ({ page, webReady, apiHealth }) => {
    test.skip(!webReady || !apiHealth.ok, 'web or API not ready');
    const username = uniqueName('e2ereg');
    const password = 'e2e_pass_123';
    await registerViaUi(page, { username, password, email: `${username}@example.test` });
    // After register, expect to be redirected away from /register.
    expect(page.url()).not.toContain('/register');
  });

  test('login with existing user and verify authenticated state', async ({ page, webReady, apiHealth }) => {
    test.skip(!webReady || !apiHealth.ok, 'web or API not ready');
    const username = process.env.E2E_USER ?? 'e2e_user';
    const password = process.env.E2E_PASS ?? 'e2e_pass_123';
    await loginViaUi(page, { username, password });
    const authed = await isAuthenticated(page);
    expect(authed).toBe(true);
  });

  test('logout clears authenticated state', async ({ page, webReady, apiHealth }) => {
    test.skip(!webReady || !apiHealth.ok, 'web or API not ready');
    const username = process.env.E2E_USER ?? 'e2e_user';
    const password = process.env.E2E_PASS ?? 'e2e_pass_123';
    await loginViaUi(page, { username, password });
    await logoutViaUi(page);
    const authed = await isAuthenticated(page);
    expect(authed).toBe(false);
  });

  test('login page rejects invalid credentials', async ({ page, webReady, apiHealth }) => {
    test.skip(!webReady || !apiHealth.ok, 'web or API not ready');
    await navigateTo(page, '/login');
    const userInput = page.locator('input[name="username"], input[name="email"], input[type="email"]').first();
    const passInput = page.locator('input[name="password"], input[type="password"]').first();
    await userInput.fill('nonexistent_user_xyz');
    await passInput.fill('wrong_password_123');
    const submit = page.locator('button[type="submit"]').first();
    await submit.click();
    // Should stay on login page or show an error.
    await page.waitForTimeout(2000);
    const stillOnLogin = page.url().includes('/login');
    const hasError = (await page.locator('text=/invalid|incorrect|error|failed/i').count()) > 0;
    expect(stillOnLogin || hasError).toBe(true);
  });

  test('protected route redirects to login when unauthenticated', async ({ page, webReady, apiHealth }) => {
    test.skip(!webReady || !apiHealth.ok, 'web or API not ready');
    await navigateTo(page, '/account');
    // Should redirect to login or show login prompt.
    await page.waitForTimeout(2000);
    const onLogin = page.url().includes('/login');
    const hasLoginPrompt = (await page.locator('text=/login|sign in/i').count()) > 0;
    expect(onLogin || hasLoginPrompt).toBe(true);
  });
});