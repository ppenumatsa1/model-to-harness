import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./mocked",
  outputDir: "../.workspace-test-results/browser",
  timeout: 30000,
  use: { baseURL: "http://127.0.0.1:5193" },
  webServer: {
    command: "npm run dev -- --mode test --host 127.0.0.1 --port 5193 --strictPort",
    env: { FRONTEND_HOST: "127.0.0.1", FRONTEND_PORT: "5193", BACKEND_PROXY_URL: "http://127.0.0.1:1" },
    url: "http://127.0.0.1:5193",
    reuseExistingServer: false
  }
});
