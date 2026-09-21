import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { checkoutEnvFile, createViteConfig, developmentSettings } from "../../vite.config";

const workRoot = resolve("node_modules/.config-tests");
const workspaces: string[] = [];
function workspace() {
  mkdirSync(workRoot, { recursive: true });
  const path = mkdtempSync(join(workRoot, "settings-"));
  workspaces.push(path);
  return path;
}
afterEach(() => {
  for (const path of workspaces.splice(0)) rmSync(path, { recursive: true, force: true });
});

describe("server-only development configuration", () => {
  it("defaults to loopback API 8030 and UI 5180 without dotenv", () => {
    expect(developmentSettings({}, null)).toEqual({
      apiTarget: "http://127.0.0.1:8030",
      host: "127.0.0.1",
      port: 5180,
      origin: "http://127.0.0.1:5180"
    });
  });

  it("discovers only the editable lane, never the cwd or an installed parent", () => {
    const root = workspace();
    const lane = join(root, "checkout-recovery/copilot-sdk");
    const frontend = join(lane, "frontend");
    mkdirSync(frontend, { recursive: true });
    writeFileSync(join(lane, "pyproject.toml"), "");
    expect(checkoutEnvFile(join(frontend, "vite.config.ts"))).toBe(join(lane, ".env"));
    expect(checkoutEnvFile(join(root, "vite.config.ts"))).toBeNull();
    expect(checkoutEnvFile(join(root, "another/maf/frontend/vite.config.ts"))).toBeNull();
  });

  it("reads only the selected file and lets process overrides win", () => {
    const root = workspace();
    const envFile = join(root, ".env");
    writeFileSync(envFile, [
      "CHECKOUT_COPILOT_API_HOST=localhost",
      "CHECKOUT_COPILOT_API_PORT=8001",
      'CHECKOUT_COPILOT_FRONTEND_ORIGIN="http://localhost:5174"',
      "APPLICATIONINSIGHTS_CONNECTION_STRING=synthetic-secret",
      "CHECKOUT_COPILOT_API_TOKEN=synthetic-secret",
      "VITE_SECRET=synthetic-secret"
    ].join("\n"));
    writeFileSync(join(root, ".env.local"), "CHECKOUT_COPILOT_API_PORT=9000");
    expect(developmentSettings({}, envFile).apiTarget).toBe("http://localhost:8001");
    const selected = developmentSettings({
      CHECKOUT_COPILOT_API_PORT: "18020",
      CHECKOUT_COPILOT_FRONTEND_ORIGIN: "http://127.0.0.1:15175",
      VITE_OTHER_SECRET: "synthetic-other"
    }, envFile);
    expect(selected).toEqual({
      apiTarget: "http://localhost:18020",
      host: "127.0.0.1",
      port: 15175,
      origin: "http://127.0.0.1:15175"
    });
    expect(JSON.stringify(selected)).not.toContain("synthetic");
    expect(developmentSettings({}, join(root, "missing.env")).port).toBe(5180);
  });

  it.each(["0", "65536", "1.5", "abc", "", "0x50"])("rejects invalid API port %s", (value) => {
    expect(() => developmentSettings({ CHECKOUT_COPILOT_API_PORT: value }, null)).toThrow("API_PORT");
  });

  it.each(["https://localhost:5180", "http://example.com", "http://0.0.0.0:5180",
    "http://localhost:5180/path", "http://user:secret@localhost:5180",
    "http://localhost:5180?secret", "http://localhost:5180#secret",
    "http://localhost:0", "http://localhost:65536", "http://localhost:5180\\evil"])(
    "rejects unsafe development origins without echoing values", (value) => {
      expect(() => developmentSettings({ CHECKOUT_COPILOT_FRONTEND_ORIGIN: value }, null))
        .toThrow("must be a loopback HTTP origin");
    }
  );

  it.each(["http://localhost", "localhost:8030", "localhost/path", "user@localhost", ""])(
    "rejects malformed proxy hosts", (value) => {
      expect(() => developmentSettings({ CHECKOUT_COPILOT_API_HOST: value }, null)).toThrow("API_HOST");
    }
  );

  it.each([["0.0.0.0", "127.0.0.1"], ["::", "[::1]"], ["::1", "[::1]"]])(
    "maps wildcard/IPv6 API host %s to a usable proxy target", (host, target) => {
      expect(developmentSettings({ CHECKOUT_COPILOT_API_HOST: host }, null).apiTarget)
        .toBe(`http://${target}:8030`);
    }
  );

  it("builds without local settings and disables automatic client env injection", () => {
    const config = createViteConfig({ command: "build" });
    expect(config.envDir).toBe(false);
    expect(config.envPrefix).toEqual([]);
    expect(config.define).toBeUndefined();
    expect(config.server).toBeUndefined();
  });

  it("applies selected ports to the strict-port same-origin development server", () => {
    const selected = developmentSettings({
      CHECKOUT_COPILOT_API_PORT: "18020",
      CHECKOUT_COPILOT_FRONTEND_ORIGIN: "http://127.0.0.1:15175"
    }, null);
    const config = createViteConfig({ command: "serve" }, selected);
    expect(config.server).toEqual({
      host: "127.0.0.1",
      port: 15175,
      origin: "http://127.0.0.1:15175",
      strictPort: true,
      proxy: { "/api": "http://127.0.0.1:18020" }
    });
    expect(config.envDir).toBe(false);
    expect(config.envPrefix).toEqual([]);
    expect(config.define).toBeUndefined();
  });
});
