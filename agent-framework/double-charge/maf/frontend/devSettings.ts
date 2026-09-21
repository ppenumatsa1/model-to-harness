import { existsSync, readFileSync } from "node:fs";
import { parseEnv } from "node:util";

function port(value: string, name: string): number {
  if (!/^\d+$/.test(value) || Number(value) < 1 || Number(value) > 65535) {
    throw new Error(`${name} must be an integer from 1 to 65535`);
  }
  return Number(value);
}

export function devSettings(envFile: string | undefined, environment = process.env) {
  const dotenv = envFile && existsSync(envFile) ? parseEnv(readFileSync(envFile, "utf8")) : {};
  const setting = (key: string, fallback: string) => environment[key] ?? dotenv[key] ?? fallback;
  const host = setting("HOST", "127.0.0.1");
  const proxyHost = host === "0.0.0.0" || host === "::" ? "127.0.0.1" : host;
  const authority = proxyHost.includes(":") ? `[${proxyHost}]` : proxyHost;
  const apiPort = port(setting("PORT", "8010"), "PORT");
  const target = setting("MAF_API_PROXY_TARGET", `http://${authority}:${apiPort}`);
  let url: URL;
  try {
    url = new URL(target);
  } catch {
    throw new Error("MAF_API_PROXY_TARGET must be an HTTP(S) origin");
  }
  if (
    !["http:", "https:"].includes(url.protocol) || url.username || url.password ||
    url.search || url.hash || url.pathname !== "/"
  ) {
    throw new Error("MAF_API_PROXY_TARGET must be an HTTP(S) origin without credentials or a path");
  }
  return {
    port: port(setting("MAF_UI_PORT", "5174"), "MAF_UI_PORT"),
    proxy: { "/api": url.origin, "/health": url.origin }
  };
}
