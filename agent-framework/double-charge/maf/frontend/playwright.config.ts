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
        command: "npm run dev -- --mode test --host 127.0.0.1 --port 5174 --strictPort",
        env: {
          HOST: "127.0.0.1",
          PORT: "8010",
          MAF_UI_PORT: "5174",
          MAF_API_PROXY_TARGET: "http://127.0.0.1:8010"
        },
        url: "http://127.0.0.1:5174",
        reuseExistingServer: false
      }
});
