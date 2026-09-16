// @vitest-environment node
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { build, loadConfigFromFile } from "vite";
import { devSettings } from "../../devSettings";

let directory: string;
beforeEach(() => { directory = mkdtempSync(join(tmpdir(), "maf-vite-config-")); });
afterEach(() => { rmSync(directory, { recursive: true, force: true }); });

describe("MAF server-only settings", () => {
  it("uses safe defaults without a dotenv", () => {
    expect(devSettings(join(directory, ".env"), {})).toEqual({
      port: 5174,
      proxy: { "/api": "http://127.0.0.1:8010", "/health": "http://127.0.0.1:8010" }
    });

  });

  it("disables dotenv in the actual Vite test-mode configuration", async () => {
    const loaded = await loadConfigFromFile(
      { command: "serve", mode: "test" },
      fileURLToPath(new URL("../../vite.config.ts", import.meta.url))
    );
    expect(loaded?.config.envDir).toBe(false);
    expect(loaded?.config.server?.proxy).toHaveProperty("/api");
    expect(devSettings(undefined, { MAF_UI_PORT: "5289" }).port).toBe(5289);
  });

  it("uses exact lane dotenv and process overrides without neighboring or mode files", () => {
    const lane = join(directory, "maf");
    mkdirSync(lane);
    writeFileSync(join(directory, ".env"), "MAF_UI_PORT=9999");
    writeFileSync(join(lane, ".env.local"), "MAF_UI_PORT=9998");
    const file = join(lane, ".env");
    writeFileSync(file, "HOST=127.0.0.2\nPORT=8123\nMAF_UI_PORT=5274\nDATABASE_URL=secret");
    expect(devSettings(file, {})).toEqual({
      port: 5274,
      proxy: { "/api": "http://127.0.0.2:8123", "/health": "http://127.0.0.2:8123" }
    });
    expect(devSettings(file, { MAF_UI_PORT: "5374", MAF_API_PROXY_TARGET: "https://api.example" }))
      .toEqual({
        port: 5374,
        proxy: { "/api": "https://api.example", "/health": "https://api.example" }
      });
  });

  it("maps wildcard bind hosts to loopback and supports IPv6", () => {
    const file = join(directory, ".env");
    expect(devSettings(file, { HOST: "0.0.0.0", PORT: "8123" }).proxy["/api"])
      .toBe("http://127.0.0.1:8123");
    expect(devSettings(file, { HOST: "::1" }).proxy["/api"]).toBe("http://[::1]:8010");
  });

  it.each(["0", "65536", "NaN", "", "12.5"])("rejects invalid UI port %s", (value) => {
    expect(() => devSettings(join(directory, ".env"), { MAF_UI_PORT: value }))
      .toThrow("MAF_UI_PORT must be");
  });

  it.each(["ftp://api.example", "http://user:secret@api.example", "http://api.example/?key=secret",
    "http://api.example/path", "secret"])("rejects unsafe proxy without echoing it", (value) => {
    try {
      devSettings(join(directory, ".env"), { MAF_API_PROXY_TARGET: value });
      expect.fail("unsafe proxy was accepted");
    } catch (error) {
      expect(String(error)).toContain("MAF_API_PROXY_TARGET must be");
      expect(String(error)).not.toContain(value);
    }
  });

  it("keeps dotenv secrets and even dotenv VITE-prefixed values out of a real build", async () => {
    writeFileSync(join(directory, ".env"),
      "DATABASE_URL=database-secret-sentinel\nVITE_SECRET=vite-secret-sentinel\n");
    writeFileSync(join(directory, "index.html"), '<script type="module" src="/main.js"></script>');
    writeFileSync(join(directory, "main.js"),
      "console.log(import.meta.env.DATABASE_URL, import.meta.env.VITE_SECRET, import.meta.env);");
    const result = await build({
      configFile: fileURLToPath(new URL("../../vite.config.ts", import.meta.url)),
      root: directory,
      logLevel: "silent",
      build: { write: false, minify: false }
    });
    const text = JSON.stringify(result);
    expect(text).not.toContain("database-secret-sentinel");
    expect(text).not.toContain("vite-secret-sentinel");
    expect(text).not.toContain("postgresql://");
  });
});
