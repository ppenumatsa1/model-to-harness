import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  use: {
    baseURL: process.env.MAF_UI_URL ?? "http://127.0.0.1:5174",
    trace: "retain-on-failure"
  },
  webServer: process.env.CI
    ? undefined
    : {
        command: "npm run dev -- --host 127.0.0.1",
        url: "http://127.0.0.1:5174",
        reuseExistingServer: true
      }
});
