import { defineConfig } from "@playwright/test";

// This suite only uses intercepted API responses on a separate local UI server.
export default defineConfig({
  testDir: "./mocked",
  outputDir: "../.workspace-test-results",
  timeout: 30000,
  use: { baseURL: "http://127.0.0.1:5189" },
  webServer: {
    command: "npm run dev -- --mode test --host 127.0.0.1 --port 5189 --strictPort",
    env: { HOST: "127.0.0.1", PORT: "8010", MAF_UI_PORT: "5189", MAF_API_PROXY_TARGET: "http://127.0.0.1:1" },
    url: "http://127.0.0.1:5189",
    reuseExistingServer: false
  }
});
