import { existsSync, readFileSync } from "node:fs";
import { isIP } from "node:net";
import { basename, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { parseEnv } from "node:util";
import { defineConfig, type ConfigEnv, type UserConfig } from "vite";
import react from "@vitejs/plugin-react";

export function checkoutEnvFile(configPath = fileURLToPath(import.meta.url)): string | null {
  const frontend = dirname(configPath);
  const lane = dirname(frontend);
  return basename(frontend) === "frontend"
    && basename(lane) === "maf"
    && basename(dirname(lane)) === "checkout-recovery"
    && existsSync(join(lane, "pyproject.toml"))
    ? join(lane, ".env")
    : null;
}

export function developmentSettings(
  environment: NodeJS.ProcessEnv = process.env,
  envFile: string | null = checkoutEnvFile()
) {
  // This module runs in Node only. Never pass dotenv or process.env to Vite's define.
  const dotenv = envFile && existsSync(envFile) ? parseEnv(readFileSync(envFile, "utf8")) : {};
  const setting = (key: string, fallback: string) => environment[key] ?? dotenv[key] ?? fallback;
  const host = setting("CHECKOUT_RECOVERY_API_HOST", "127.0.0.1");
  const portText = setting("CHECKOUT_RECOVERY_API_PORT", "8000").trim();
  const port = Number(portText);
  if (!/^\d+$/.test(portText) || !Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error("CHECKOUT_RECOVERY_API_PORT must be an integer between 1 and 65535.");
  }
  const hostname = host.length <= 253 && host.split(".").every(
    (label) => /^[a-z\d](?:[a-z\d-]{0,61}[a-z\d])?$/i.test(label)
  );
  if (!isIP(host) && !hostname) {
    throw new Error("CHECKOUT_RECOVERY_API_HOST must be an IP address or hostname.");
  }
  const targetHost = host === "0.0.0.0" ? "127.0.0.1" : host === "::" ? "::1" : host;
  const apiTarget = `http://${isIP(targetHost) === 6 ? `[${targetHost}]` : targetHost}:${port}`;
  const originText = setting("CHECKOUT_RECOVERY_FRONTEND_ORIGIN", "http://127.0.0.1:5173");
  let origin: URL;
  try {
    origin = new URL(originText);
    if (
      origin.protocol !== "http:"
      || !["127.0.0.1", "localhost", "[::1]"].includes(origin.hostname)
      || origin.username || origin.password || origin.pathname !== "/"
      || origin.search || origin.hash || /[\s\\?#]/.test(originText)
      || Number(origin.port || 80) < 1
    ) {
      throw new Error();
    }
  } catch {
    throw new Error("CHECKOUT_RECOVERY_FRONTEND_ORIGIN must be a loopback HTTP origin without credentials or a path.");
  }
  return {
    apiTarget,
    host: origin.hostname.replace(/^\[|\]$/g, ""),
    port: Number(origin.port || 80),
    origin: origin.origin
  };
}

export function createViteConfig(
  { command }: Pick<ConfigEnv, "command">,
  settings?: ReturnType<typeof developmentSettings>
): UserConfig {
  const development = command === "serve" ? settings ?? developmentSettings() : undefined;
  return {
    plugins: [react()],
    envDir: false,
    envPrefix: [],
    server: development ? {
      host: development.host,
      port: development.port,
      origin: development.origin,
      strictPort: true,
      proxy: { "/api": development.apiTarget }
    } : undefined
  };
}

export default defineConfig(createViteConfig);
