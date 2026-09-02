import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  use: {
    baseURL: process.env.UI_BASE_URL ?? "http://127.0.0.1:5173",
    trace: "retain-on-failure"
  }
});

