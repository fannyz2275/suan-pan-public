import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: "list",
  // Only run globalSetup/globalTeardown when eval mode is requested.
  // Standard smoke/recurring tests skip setup by not requiring storageState.
  globalSetup: process.env.EVAL_MOCKS === "1" ? "./e2e/global-setup.ts" : undefined,
  globalTeardown: process.env.EVAL_MOCKS === "1" ? "./e2e/global-teardown.ts" : undefined,
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE || "http://localhost:5173",
    trace: "retain-on-failure",
    // Persist login state across portfolio spec files when available.
    storageState: process.env.EVAL_MOCKS === "1" ? "e2e/.auth.json" : undefined,
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
