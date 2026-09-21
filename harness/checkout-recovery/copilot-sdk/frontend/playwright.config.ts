import { defineConfig, devices } from "@playwright/test";

const remoteUrl = process.env.CHECKOUT_E2E_BASE_URL;
const username = process.env.CHECKOUT_UI_USERNAME;
const password = process.env.CHECKOUT_UI_PASSWORD;
if (Boolean(username) !== Boolean(password)) {
  throw new Error("Provide both CHECKOUT_UI_USERNAME and CHECKOUT_UI_PASSWORD.");
}

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 360_000,
  expect: { timeout: 30_000 },
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: remoteUrl || "http://127.0.0.1:5180",
    httpCredentials: username && password ? { username, password } : undefined,
    // Traces/HAR can retain authentication headers; do not record credential-bearing traffic.
    trace: "off",
    screenshot: "only-on-failure",
    video: "off"
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: remoteUrl ? undefined : {
    command: "npm run dev -- --host 127.0.0.1 --port 5180 --strictPort",
    url: "http://127.0.0.1:5180",
    reuseExistingServer: !process.env.CI,
    timeout: 60_000
  }
});
