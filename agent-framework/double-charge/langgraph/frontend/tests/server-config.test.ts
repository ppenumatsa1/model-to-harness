// @vitest-environment node
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { readServerValues, serverConfig } from "../server-config";

describe("lane-local server configuration", () => {
  it("retains defaults and proxies readiness", () => {
    expect(serverConfig({}, {})).toEqual({
      host: "localhost", port: 5173, strictPort: true,
      proxy: {
        "/api": "http://127.0.0.1:8000",
        "/health": "http://127.0.0.1:8000",
        "/ready": "http://127.0.0.1:8000"
      }
    });
  });

  it("applies process over dotenv and derives the backend port", () => {
    const config = serverConfig(
      { FRONTEND_PORT: "5200", PORT: "8100", HOST: "0.0.0.0" },
      { FRONTEND_PORT: "5201", FRONTEND_HOST: "127.0.0.1", PORT: "8101" }
    );
    expect(config.port).toBe(5201);
    expect(config.host).toBe("127.0.0.1");
    expect(config.proxy["/api"]).toBe("http://127.0.0.1:8101");
    expect(serverConfig({ BACKEND_PROXY_URL: "http://localhost:8100" }, {
      BACKEND_PROXY_URL: "https://backend.test"
    }).proxy["/api"]).toBe("https://backend.test");
  });

  it("supports IPv6 loopback and wildcard binds", () => {
    expect(serverConfig({ HOST: "::1" }, {}).proxy["/api"]).toBe("http://[::1]:8000");
    expect(serverConfig({ HOST: "::" }, {}).proxy["/api"]).toBe("http://127.0.0.1:8000");
  });

  it.each(["0", "65536", "-1", "abc", "3.5", ""])("rejects invalid ports: %s", (value) => {
    expect(() => serverConfig({ FRONTEND_PORT: value }, {})).toThrow("FRONTEND_PORT");
    expect(() => serverConfig({ PORT: value }, {})).toThrow("PORT");
  });

  it.each(["ftp://backend.test", "http://user:pass@backend.test", "not-a-url",
    "http://backend.test/path", "http://backend.test?secret=value", "http://backend.test#fragment"
  ])("rejects unsafe proxy origins", (value) => {
    expect(() => serverConfig({ BACKEND_PROXY_URL: value }, {})).toThrow("BACKEND_PROXY_URL");
  });

  it("selects only safe server keys from the exact dotenv file", () => {
    const directory = mkdtempSync(join(tmpdir(), "langgraph-server-"));
    try {
      const path = join(directory, ".env");
      writeFileSync(path,
        "FRONTEND_PORT=5210\nPORT=8110\nDATABASE_URL=PRIVATE_DB\n" +
        "APPLICATIONINSIGHTS_CONNECTION_STRING=PRIVATE_TELEMETRY\nVITE_SECRET=PRIVATE_PUBLIC\n");
      writeFileSync(join(directory, ".env.local"), "FRONTEND_PORT=9999\n");
      expect(readServerValues(path)).toEqual({ FRONTEND_PORT: "5210", PORT: "8110" });
      expect(JSON.stringify(serverConfig(readServerValues(path), {}))).not.toContain("PRIVATE");
      expect(readServerValues(join(directory, "missing.env"))).toEqual({});
      expect(() => readServerValues(directory)).toThrow("Cannot read LangGraph");
    } finally {
      rmSync(directory, { recursive: true });
    }
  });
});
