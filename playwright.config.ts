import { defineConfig, devices } from '@playwright/test'

// End-to-end tests run against a throwaway stack: a seeded SQLite API on :8001 (see e2e/start-api.mjs) and the Vite dev
// server on :5174 pointed at it. Nothing touches backend/.env, PostgreSQL, Stripe or any outside service.
export default defineConfig({
  testDir: './e2e',
  testMatch: '**/*.spec.ts',
  fullyParallel: false, // one shared database; specs create their own users so order does not matter, but the stream limit is per account only
  workers: 1,
  retries: 0,
  timeout: 45_000,
  expect: { timeout: 8_000 },
  reporter: [['list'], ['json', { outputFile: 'e2e/results.json' }]],
  use: { baseURL: 'http://localhost:5174', trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  projects: [{ name: 'desktop', use: { ...devices['Desktop Chrome'] } }, { name: 'mobile', use: { ...devices['Pixel 7'] }, grep: /@mobile/ }],
  webServer: [
    { command: 'node e2e/start-api.mjs', url: 'http://localhost:8001/api/v1/catalog/genres', timeout: 120_000, reuseExistingServer: false },
    { command: 'npx vite --port 5174 --strictPort', url: 'http://localhost:5174', timeout: 60_000, reuseExistingServer: false, env: { VITE_DEV_API: 'http://localhost:8001' } },
  ],
})
