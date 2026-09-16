import { readFileSync } from "node:fs";
import { parseEnv } from "node:util";
import { fileURLToPath } from "node:url";

const laneEnv = fileURLToPath(new URL("../.env", import.meta.url));
const serverKeys = ["HOST", "PORT", "FRONTEND_HOST", "FRONTEND_PORT", "BACKEND_PROXY_URL"] as const;
type ServerValues = Partial<Record<(typeof serverKeys)[number], string>>;

export function readServerValues(path = laneEnv): ServerValues {
  let content: string;
  try {
    content = readFileSync(path, "utf8");
  } catch (error) {
    if (error instanceof Error && "code" in error && error.code === "ENOENT") return {};
    throw new Error("Cannot read LangGraph lane server configuration");
  }
  const parsed = parseEnv(content);
  return Object.fromEntries(serverKeys.filter((key) => key in parsed).map((key) => [key, parsed[key]]));
}

function port(value: string | undefined, fallback: number, name: string): number {
  if (value === undefined) return fallback;
  const number = Number(value);
  if (!/^\d+$/.test(value) || !Number.isInteger(number) || number < 1 || number > 65535) {
    throw new Error(`${name} must be an integer between 1 and 65535`);
  }
  return number;
}

export function serverConfig(
  dotenv: ServerValues = readServerValues(),
  environment: NodeJS.ProcessEnv = process.env
) {
  const value = (key: (typeof serverKeys)[number]) => environment[key] ?? dotenv[key];
  const host = value("FRONTEND_HOST") ?? "localhost";
  if (!host.trim()) throw new Error("FRONTEND_HOST must not be empty");
  const backendHost = value("HOST") ?? "127.0.0.1";
  const connectHost = ["0.0.0.0", "::"].includes(backendHost) ? "127.0.0.1" : backendHost;
  const authority = connectHost.includes(":") ? `[${connectHost}]` : connectHost;
  const target = value("BACKEND_PROXY_URL") ??
    `http://${authority}:${port(value("PORT"), 8000, "PORT")}`;
  let proxy: URL;
  try {
    proxy = new URL(target);
  } catch {
    throw new Error("BACKEND_PROXY_URL must be an HTTP(S) origin without credentials");
  }
  if (!["http:", "https:"].includes(proxy.protocol) || proxy.username || proxy.password ||
      proxy.pathname !== "/" || proxy.search || proxy.hash) {
    throw new Error("BACKEND_PROXY_URL must be an HTTP(S) origin without credentials");
  }
  return {
    host,
    port: port(value("FRONTEND_PORT"), 5173, "FRONTEND_PORT"),
    strictPort: true,
    proxy: { "/api": proxy.origin, "/health": proxy.origin, "/ready": proxy.origin }
  };
}
