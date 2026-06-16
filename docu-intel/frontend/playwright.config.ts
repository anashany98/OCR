import { defineConfig, devices } from "@playwright/test"

/**
 * S3.3 (Sprint 3) — Playwright e2e configuration.
 *
 * The tests are designed to run against a fully-running stack
 * (backend + frontend + Postgres + Redis + Celery). The CI
 * workflow launches the backend with ``docker compose up
 * --profile e2e`` and the frontend via ``vite preview`` (the
 * built dist served by nginx in production). Locally the
 * same ``docker compose up`` works.
 *
 * Two ways to skip the e2e setup:
 *
 *   - ``SKIP_E2E=1 npm run test:e2e`` exits 0 without running
 *     anything. Use this in CI jobs that don't have the full
 *     stack available (lint, unit tests, etc).
 *   - ``PLAYWRIGHT_BASE_URL=http://localhost:5173 npm run
 *     test:e2e`` overrides the base URL. The default
 *     ``http://localhost:8080`` matches the prod frontend
 *     port.
 */
const skipE2E = Boolean(process.env.SKIP_E2E)
const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:8080"

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  // ``SKIP_E2E`` short-circuits the whole runner; we leave
  // ``testIgnore`` to honour it when running locally too.
  testIgnore: skipE2E ? ["**/*.spec.ts", "**/*.test.ts"] : undefined,
  use: {
    baseURL,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: process.env.PLAYWRIGHT_NO_WEBSERVER
    ? undefined
    : {
        // The frontend is served by nginx (port 8080 in prod
        // compose) or by ``vite preview`` (port 4173 in
        // dev). CI launches the full stack via docker compose
        // so we do NOT spawn a webserver here — the
        // ``baseURL`` points at an already-running one.
        command: "echo 'frontend served externally; nothing to spawn'",
        url: baseURL,
        reuseExistingServer: true,
        timeout: 5_000,
      },
})
