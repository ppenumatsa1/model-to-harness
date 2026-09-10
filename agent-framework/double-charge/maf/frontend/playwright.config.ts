import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 180_000,
  expect: { timeout: 60_000 },
  use: {
    baseURL: process.env.MAF_UI_URL ?? "http://127.0.0.1:5174",
    trace: "retain-on-failure"
  },
  webServer: process.env.CI || process.env.MAF_UI_URL
    ? undefined
    : {
        command: "npm run dev -- --host 127.0.0.1",
        url: "http://127.0.0.1:5174",
        reuseExistingServer: true
      }
});
