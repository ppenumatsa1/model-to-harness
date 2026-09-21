import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { devSettings } from "./devSettings";

export default defineConfig(({ command, mode }) => ({
  root: fileURLToPath(new URL(".", import.meta.url)),
  envDir: false,
  plugins: [react()],
  server: command === "serve"
    ? devSettings(mode === "test" ? undefined : fileURLToPath(new URL("../.env", import.meta.url)))
    : undefined
}));
