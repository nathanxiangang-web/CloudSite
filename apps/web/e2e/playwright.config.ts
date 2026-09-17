import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright E2E configuration for CloudSite web app.
 *
 * Targets:
 *   - web: http://localhost:3000 (Next.js dev/start)
 *   - api: http://localhost:8000 (FastAPI backend)
 *
 * Tests are automatically skipped when the API is not reachable.
 * See helpers.ts -> waitForApiReady for the gate logic.
 */

const WEB_BASE_URL = process.env.E2E_WEB_URL ?? 'http://localhost:3000';
const API_BASE_URL = process.env.E2E_API_URL ?? 'http://localhost:8000';

export default defineConfig({
  testDir: '.',
  testMatch: /.*\.spec\.ts$/,

  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,

  reporter: [
    ['list'],
    ['html', { outputFolder: 'e2e-report', open: 'never' }],
  ],

  timeout: 60_000,
  expect: { timeout: 10_000 },

  use: {
    baseURL: WEB_BASE_URL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
    extraHTTPHeaders: {
      'X-E2E-Run': '1',
    },
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  // No webServer auto-start: tests must be skippable if API/web are down.
  // Start `pnpm dev` (web) and the API server manually before running e2e.
});

export { WEB_BASE_URL, API_BASE_URL };