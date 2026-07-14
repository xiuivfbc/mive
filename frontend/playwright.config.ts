import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  reporter: 'list',

  globalSetup: './e2e/global-setup.ts',
  globalTeardown: './e2e/global-teardown.ts',

  use: {
    baseURL: 'http://127.0.0.1:5173',
    trace: 'on-first-retry',
    ...devices['Desktop Chrome'],
    channel: 'chromium',
    headless: true,
    actionTimeout: 15_000,
  },

  webServer: {
    command: 'node ../scripts/start-test-servers.mjs',
    url: 'http://127.0.0.1:5173',
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
